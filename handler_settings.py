# ruff: noqa: F403, F405

import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from constants import *
from handler_delete import schedule_delete_with_undo
from handler_lists import fetch_posts_for_user
from handler_posts import _submit_create_post, _submit_update_post
from handler_state import gate_callback, get_list_state, set_list_state
from handler_ui import build_list_message
from handler_utils import (
    api_call,
    ensure_allowed,
    ensure_api_key_or_prompt,
    ensure_private,
    get_effective_preview_length,
    http_2xx,
    invalid_slug_text,
    is_valid_slug,
    payload_ok,
    safe_chat_id,
    save_users_data,
    with_status,
)
from storage import users_data

logger = logging.getLogger(__name__)

def build_settings_text(user_id: int) -> str:
    u = users_data[user_id]
    return (
        f"{MESSAGES['SETTINGS_HEADER']}\n"
        f"- Default publish mode: {u.settings.get('default_publish_mode', 'draft')}\n"
        f"- Preview length: {u.settings.get('preview_length', DEFAULT_PREVIEW_LENGTH)}\n"
        f"- Preview format: {u.settings.get('preview_format', 'markdown')}\n"
        f"- Confirm before delete: {u.settings.get('confirm_before_delete', True)}\n"
    )


def build_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(MESSAGES["BUTTON_TOGGLE_DEFAULT_MODE"], callback_data=CB_SETTINGS_MODE)],
            [
                InlineKeyboardButton("Preview 140", callback_data=f"{CB_SETTINGS_PREV_PREFIX}140"),
                InlineKeyboardButton("280", callback_data=f"{CB_SETTINGS_PREV_PREFIX}280"),
                InlineKeyboardButton("500", callback_data=f"{CB_SETTINGS_PREV_PREFIX}500"),
            ],
            [InlineKeyboardButton(MESSAGES["BUTTON_TOGGLE_PREVIEW_FORMAT"], callback_data=CB_SETTINGS_FORMAT)],
            [InlineKeyboardButton(MESSAGES["BUTTON_TOGGLE_CONFIRM_DELETE"], callback_data=CB_SETTINGS_CONFIRM)],
        ]
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    await update.message.reply_text(build_settings_text(user_id), reply_markup=build_settings_keyboard(user_id))


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    if not await gate_callback(query, context):
        return
    # Ensure API key configured
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    u = users_data[user_id]
    parts = query.data.split(":")
    if len(parts) >= 2 and parts[1] == "mode":
        u.settings["default_publish_mode"] = (
            "publish" if u.settings.get("default_publish_mode") == "draft" else "draft"
        )
    elif len(parts) >= 2 and parts[1] == "format":
        u.settings["preview_format"] = (
            "plain" if u.settings.get("preview_format", "markdown") == "markdown" else "markdown"
        )
    elif len(parts) >= 3 and parts[1] == "prev":
        try:
            val = int(parts[2])
            if val in ALLOWED_PREVIEW_LENGTHS:
                u.settings["preview_length"] = val
        except Exception:
            pass
    elif len(parts) >= 2 and parts[1] == "confirm":
        u.settings["confirm_before_delete"] = not u.settings.get(
            "confirm_before_delete", True
        )
    await save_users_data()
    # Re-render
    try:
        await query.edit_message_text(build_settings_text(user_id), reply_markup=build_settings_keyboard(user_id))
    except Exception:
        pass


# ----- Status -----
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    api_key = users_data[user_id].api_key
    t1 = time.time()
    response, _ = await api_call("GET", api_key, context=context, chat_id=safe_chat_id(update))
    t2 = time.time()
    if http_2xx(response):
        await update.message.reply_text(MESSAGES["STATUS_API_REACHABLE"].format(ms=int((t2 - t1)*1000)))
    else:
        await update.message.reply_text(with_status(MESSAGES["STATUS_API_UNREACHABLE"], response))


# ----- Retry Handler -----
async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    if not await gate_callback(query, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    last = users_data.get(user_id).last_action if users_data.get(user_id) else None
    if not last:
        await query.edit_message_text(MESSAGES["NO_ACTION_TO_RETRY"])
        return
    t = last.get("type")
    api_key = users_data[user_id].api_key
    chat_id = safe_chat_id(query=query)
    if t == "create":
        # Reuse context.user_data fields
        context.user_data[K_TITLE] = last.get("payload", {}).get(
            "title", context.user_data.get(K_TITLE)
        )
        context.user_data[K_BODY] = last.get("payload", {}).get(
            "body", context.user_data.get(K_BODY)
        )
        context.user_data[K_PUBLISHED_AT] = last.get("payload", {}).get(
            "published_at", context.user_data.get(K_PUBLISHED_AT)
        )
        await _submit_create_post(query, context)
    elif t == "update":
        context.user_data[K_PUBLISHED_AT] = last.get("payload", {}).get("published_at")
        context.user_data[K_TITLE] = last.get("payload", {}).get("title")
        context.user_data[K_BODY] = last.get("payload", {}).get("body")
        context.user_data[K_FINAL_SLUG] = last.get("payload", {}).get("slug", last.get("slug"))
        context.user_data[K_CURRENT_SLUG] = last.get("slug")
        await _submit_update_post(query, context)
    elif t == "togglepub":
        slug = last.get("slug")
        payload = last.get("payload", {})
        if not is_valid_slug(slug or ""):
            await query.edit_message_text(invalid_slug_text())
            return
        response, data = await api_call(
            "PATCH", api_key, slug=slug, payload=payload, context=context, chat_id=chat_id
        )
        if http_2xx(response) or payload_ok(data):
            # Refresh list if possible
            context.user_data.pop(K_POSTS_CACHE, None)
            state = get_list_state(context)
            posts, _ = await fetch_posts_for_user(user_id, context, chat_id=chat_id)
            if posts is not None:
                preview_len = get_effective_preview_length(user_id)
                text, markup, page_used = build_list_message(
                    posts,
                    state.get("filter", "all"),
                    state.get("page", 1),
                    state.get("query"),
                    preview_len,
                    context,
                    user_id,
                )
                state["page"] = page_used
                set_list_state(context, state)
                await query.edit_message_text(
                    text, reply_markup=markup, disable_web_page_preview=True, parse_mode="MarkdownV2"
                )
            else:
                await query.edit_message_text(MESSAGES["TOGGLED_PUBLISH_STATE"])
            try:
                users_data[user_id].last_action = {}
                await save_users_data()
            except Exception:
                pass
        else:
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(MESSAGES["BUTTON_RETRY"], callback_data=CB_RETRY_TOGGLEPUB)]]
            )
            await query.edit_message_text(
                with_status(MESSAGES["FAILED_TOGGLE_PUBLISH"], response), reply_markup=keyboard
            )
    elif t == "delete":
        slug = last.get("slug")
        if not is_valid_slug(slug or ""):
            await query.edit_message_text(invalid_slug_text())
            return
        await schedule_delete_with_undo(query, context, slug)
    else:
        await query.edit_message_text(MESSAGES["UNSUPPORTED_RETRY"])


# ----- Global Error Handler -----
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = None
        if isinstance(update, Update) and update.effective_user:
            uid = update.effective_user.id
        logger.error("Error for user %s: %s", uid, getattr(context, "error", None))
    except Exception:
        logger.error("Unhandled error: %s", getattr(context, "error", None))
