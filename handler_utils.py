# ruff: noqa: F403, F405

import asyncio
from datetime import datetime
from functools import lru_cache
import logging
import os
import re
import time
from json import JSONDecodeError
from typing import Any, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.helpers import escape_markdown
from telegram.ext import ContextTypes

from constants import *
from storage import UserData, save_users_data, users_data

logger = logging.getLogger(__name__)
_http_client: Optional[httpx.AsyncClient] = None

def get_user_id(update: Update) -> Optional[int]:
    """Return the effective user id from update if available."""
    if update.effective_user:
        return update.effective_user.id
    return None


def extract_message_text(message: Any) -> str:
    """Return message text with formatting preserved when possible."""
    if message is None:
        return ""
    text = getattr(message, "text", None)
    if not isinstance(text, str) or not text:
        return ""
    entities = getattr(message, "entities", None)
    if entities:
        for attr in ("text_markdown", "text_markdown_v2"):
            try:
                val = getattr(message, attr, None)
            except Exception:
                continue
            if isinstance(val, str) and val:
                return val
    return text


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient()
    return _http_client


async def close_http_client(_: Optional[Any] = None) -> None:
    global _http_client
    if _http_client is not None:
        try:
            await _http_client.aclose()
        except Exception:
            pass
        _http_client = None


async def _run_save_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        context.application.bot_data.pop(K_SAVE_JOB, None)
    except Exception:
        pass
    await save_users_data()


async def schedule_users_data_save(
    context: ContextTypes.DEFAULT_TYPE, delay: float = SAVE_DEBOUNCE_SEC
) -> None:
    try:
        job_queue = context.job_queue
        bot_data = context.application.bot_data
    except Exception:
        await save_users_data()
        return
    job = bot_data.get(K_SAVE_JOB)
    if job and getattr(job, "enabled", True):
        return
    try:
        bot_data[K_SAVE_JOB] = job_queue.run_once(_run_save_job, delay)
    except Exception:
        await save_users_data()


@lru_cache(maxsize=1)
def allowed_user_ids() -> Optional[Set[int]]:
    raw_allowed = os.getenv("MATAROA_BOT_ALLOWED_USERS", "").strip()
    if not raw_allowed:
        return None
    allowed: Set[int] = set()
    for part in raw_allowed.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError:
            logger.warning("Ignoring invalid MATAROA_BOT_ALLOWED_USERS entry: %s", part)
    return allowed


async def ensure_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    allowed = allowed_user_ids()
    if allowed is None:
        return True
    user_id = get_user_id(update)
    if user_id in allowed:
        return True
    if update.callback_query:
        try:
            await update.callback_query.answer(MESSAGES["ACCESS_DENIED"], show_alert=True)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(MESSAGES["ACCESS_DENIED"])
    return False


def slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_RE.match(slug))


def truncate(text: str, length: int) -> str:
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)] + "…"


def now_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def clamp_button_text(label: str, max_len: int = MAX_BUTTON_TEXT) -> str:
    if len(label) <= max_len:
        return label
    return truncate(label, max_len)


def cooldown_ok(
    context: ContextTypes.DEFAULT_TYPE, key: str = "tap", threshold: float = DRAFT_COOLDOWN_SEC
) -> bool:
    """Return True if monotonic cooldown window has elapsed for the provided key."""
    now = time.monotonic()
    last = context.user_data.get(f"last_{key}", 0.0)
    if now - last < threshold:
        return False
    context.user_data[f"last_{key}"] = now
    return True


async def send_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Send a typing indicator; ignore failures."""
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass


def is_valid_absolute_url(url: str) -> bool:
    try:
        u = urlparse(url)
        return u.scheme in ("http", "https") and bool(u.netloc)
    except Exception:
        return False


def mdv2(s: str) -> str:
    return escape_markdown(s or "", version=2)


def safe_truncate_md(s: str, max_len: int) -> str:
    """Truncate a MarkdownV2 string to max_len, avoiding dangling escape backslashes."""
    if max_len <= 0:
        return ""
    if max_len == 1:
        return "…"
    if len(s) <= max_len:
        return s
    cut = max_len - 1
    while cut > 0 and s[cut - 1] == "\\":
        cut -= 1
    return s[:cut] + "…"


def safe_truncate_text(s: str, max_len: int) -> str:
    """Truncate a plain string to max_len."""
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)] + "…"


def get_effective_preview_length(user_id: int) -> int:
    """Return user's preview length if valid else DEFAULT_PREVIEW_LENGTH."""
    val = users_data.get(user_id, UserData(api_key="")).settings.get(
        "preview_length", DEFAULT_PREVIEW_LENGTH
    )
    if isinstance(val, int) and val in ALLOWED_PREVIEW_LENGTHS:
        return val
    return DEFAULT_PREVIEW_LENGTH


def get_preview_format(user_id: int) -> str:
    val = users_data.get(user_id, UserData(api_key="")).settings.get(
        "preview_format", "markdown"
    )
    return val if isinstance(val, str) and val in ALLOWED_PREVIEW_FORMATS else "markdown"


async def ensure_api_key_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Ensure the user has an API key; prompt in message or alert in callback if missing."""
    uid = get_user_id(update)
    if uid is None:
        return None
    u = users_data.get(uid)
    if not u or not (u.api_key or "").strip():
        if update.callback_query:
            try:
                await update.callback_query.answer(
                    MESSAGES["NEED_API_KEY"], show_alert=True
                )
            except Exception:
                pass
        elif update.message:
            await update.message.reply_text(MESSAGES["NEED_API_KEY"])
        return None
    return uid


def safe_chat_id(update: Optional[Update] = None, query: Optional[Any] = None) -> Optional[int]:
    """Return chat_id from Update or CallbackQuery if available."""
    if query is not None and getattr(query, "message", None) is not None:
        return query.message.chat_id
    if update is not None:
        if getattr(update, "message", None) is not None:
            return update.message.chat_id
        if getattr(update, "effective_chat", None) is not None and update.effective_chat is not None:
            return update.effective_chat.id
    return None
async def api_call(
    method: str,
    api_key: str,
    slug: Optional[str] = None,
    payload: Optional[dict] = None,
    *,
    retry: bool = True,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    chat_id: Optional[int] = None,
) -> Tuple[Optional[httpx.Response], Optional[dict]]:
    """Call Mataroa API and return (response, parsed_json) with a single retry on error."""
    url = API_URL if slug is None else f"{API_URL}{slug}/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def _request_once() -> Tuple[Optional[httpx.Response], Optional[dict]]:
        client = get_http_client()
        response = await client.request(
            method, url, headers=headers, json=payload, timeout=HTTP_TIMEOUT
        )
        data = None
        if response is not None:
            if response.status_code == 204:
                return response, None
            ct = (response.headers.get("Content-Type", "") or "").lower()
            if response.content and "application/json" in ct:
                try:
                    data = response.json()
                except JSONDecodeError:
                    data = None
        return response, data

    if context and chat_id:
        await send_typing(context, chat_id)
    attempts = 0
    while True:
        try:
            response, data = await _request_once()
        except httpx.HTTPError as e:
            logger.error("API call error: %s", e)
            if retry and attempts < API_MAX_RETRIES:
                await asyncio.sleep(API_RETRY_BACKOFF * (2 ** attempts))
                attempts += 1
                continue
            return None, None
        if not retry:
            return response, data
        status = response.status_code if response is not None else None
        if status is not None and (status == 429 or status >= 500):
            if attempts < API_MAX_RETRIES:
                await asyncio.sleep(API_RETRY_BACKOFF * (2 ** attempts))
                attempts += 1
                continue
        return response, data


# ---------- Token Mapping Helpers ----------

def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


async def ensure_private(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message: str = MESSAGES["PRIVACY_DM"]
) -> bool:
    if is_private_chat(update):
        return True
    if update.callback_query:
        try:
            await update.callback_query.answer(message, show_alert=True)
        except Exception:
            pass
    if getattr(update, "message", None):
        try:
            await update.message.reply_text(message)
        except Exception:
            pass
    return False


# ---------- HTTP/Response Helpers ----------

def http_2xx(response: Optional[httpx.Response]) -> bool:
    return bool(response is not None and 200 <= response.status_code < 300)


def payload_ok(data: Optional[dict]) -> bool:
    return isinstance(data, dict) and bool(data.get("ok"))


def with_status(message: str, response: Optional[httpx.Response]) -> str:
    if response is None:
        return message
    try:
        return f"{message} (HTTP {response.status_code})"
    except Exception:
        return message


# ---------- Messaging Helper ----------
async def send_or_edit(
    text: str,
    *,
    update: Optional[Update] = None,
    query: Optional[Any] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    markdown: bool = False,
    escape_user: bool = False,
    disable_web_preview: bool = True,
) -> None:
    """Send a message or edit an existing callback message with consistent options."""
    try:
        pm = "MarkdownV2" if markdown else None
        to_send = mdv2(text) if (markdown and escape_user) else text
        if query is not None:
            await query.edit_message_text(
                to_send,
                reply_markup=reply_markup,
                parse_mode=pm,
                disable_web_page_preview=disable_web_preview,
            )
            return
        if update is not None and getattr(update, "message", None) is not None:
            await update.message.reply_text(
                to_send,
                reply_markup=reply_markup,
                parse_mode=pm,
                disable_web_page_preview=disable_web_preview,
            )
    except Exception:
        pass


def invalid_slug_text() -> str:
    return MESSAGES["INVALID_SLUG"]


def stale_action_text() -> str:
    return MESSAGES["INVALID_OR_STALE_ACTION"]
