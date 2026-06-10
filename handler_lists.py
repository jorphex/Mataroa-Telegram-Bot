# ruff: noqa: F403, F405

import time
from typing import List, Optional, Tuple

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from constants import *
from handler_state import (
    gate_callback,
    get_list_state,
    resolve_token_to_slug,
    set_list_state,
)
from handler_ui import build_list_message, build_manage_post_view
from handler_utils import (
    api_call,
    cooldown_ok,
    ensure_allowed,
    ensure_api_key_or_prompt,
    ensure_private,
    get_effective_preview_length,
    http_2xx,
    is_valid_slug,
    payload_ok,
    safe_chat_id,
    send_typing,
    stale_action_text,
    with_status,
)
from storage import users_data

async def fetch_posts_for_user(
    user_id: int, context: ContextTypes.DEFAULT_TYPE, *, chat_id: Optional[int] = None
) -> Tuple[Optional[List[dict]], Optional[httpx.Response]]:
    api_key = users_data[user_id].api_key
    # Cache to reduce API calls
    cache = context.user_data.get(K_POSTS_CACHE)
    if cache and time.time() - cache.get("ts", 0) < POSTS_CACHE_TTL:
        return cache.get("posts"), None
    response, data = await api_call("GET", api_key, context=context, chat_id=chat_id)
    posts: Optional[List[dict]] = None
    if http_2xx(response):
        if isinstance(data, dict) and isinstance(data.get("post_list"), list):
            posts = data.get("post_list", [])
        elif isinstance(data, list):
            posts = data
    elif payload_ok(data) and isinstance(data, dict):
        if isinstance(data.get("post_list"), list):
            posts = data.get("post_list")
    if posts is not None:
        context.user_data[K_POSTS_CACHE] = {"ts": time.time(), "posts": posts}
        return posts, response
    return None, response


async def list_posts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    filter_mode: str = "all",
    query: Optional[str] = None,
) -> None:
    """Render the paginated posts list for a user into the chat."""
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    posts, response = await fetch_posts_for_user(user_id, context, chat_id=safe_chat_id(update))
    if posts is None:
        await update.message.reply_text(with_status(MESSAGES["FAILED_FETCH_POSTS"], response))
        return
    page = 1
    preview_len = get_effective_preview_length(user_id)
    text, markup, page_used = build_list_message(
        posts, filter_mode, page, query, preview_len, context, user_id
    )
    set_list_state(context, {"filter": filter_mode, "page": page_used, "query": query})
    await update.message.reply_text(
        text, reply_markup=markup, disable_web_page_preview=True, parse_mode="MarkdownV2"
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # /list [published|drafts]
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    if not cooldown_ok(context, key="list", threshold=LIST_COOLDOWN_SEC):
        if update.message:
            await update.message.reply_text(MESSAGES["PLEASE_WAIT"])
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    arg = (context.args[0].lower() if context.args else "all")
    if arg not in ("all", "published", "drafts"):
        arg = "all"
    await list_posts(update, context, filter_mode=arg)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    if not cooldown_ok(context, key="list", threshold=LIST_COOLDOWN_SEC):
        if update.message:
            await update.message.reply_text(MESSAGES["PLEASE_WAIT"])
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    if not context.args:
        await update.message.reply_text(MESSAGES["USAGE_SEARCH"])
        return
    query = " ".join(context.args).strip()
    await list_posts(update, context, filter_mode="all", query=query)


async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination/filter interactions in the posts list view."""
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
    chat_id = safe_chat_id(query=query)
    posts, response = await fetch_posts_for_user(user_id, context, chat_id=chat_id)
    if posts is None:
        await query.edit_message_text(with_status(MESSAGES["FAILED_FETCH_POSTS"], response))
        return
    state = get_list_state(context)
    qd = query.data
    if qd.startswith(CB_LIST_FILTER_PREFIX):
        state["filter"] = qd[len(CB_LIST_FILTER_PREFIX):]
        state["page"] = 1
    elif qd.startswith(CB_LIST_PAGE_PREFIX):
        suffix = qd[len(CB_LIST_PAGE_PREFIX):]
        if suffix == "next":
            state["page"] = state.get("page", 1) + 1
        elif suffix == "prev":
            state["page"] = max(1, state.get("page", 1) - 1)
    elif qd == CB_LIST_REFRESH:
        # Clear cache
        context.user_data.pop(K_POSTS_CACHE, None)
        posts, response = await fetch_posts_for_user(user_id, context, chat_id=chat_id)
        if posts is None:
            await query.edit_message_text(with_status(MESSAGES["FAILED_FETCH_POSTS"], response))
            return
    elif qd.startswith(f"{CB_LIST_PREFIX}manage:"):
        tok = qd.split(":", 2)[2] if ":" in qd else ""
        slug = resolve_token_to_slug(context, user_id, tok) if tok else None
        if not slug or not is_valid_slug(slug):
            await query.edit_message_text(stale_action_text())
            return
        post = next((p for p in posts if p.get("slug") == slug), None)
        text, markup = build_manage_post_view(post or {}, slug, context, user_id)
        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return
    elif qd == f"{CB_LIST_PREFIX}back":
        # Just re-render list using existing state
        pass
    else:
        # Unknown within list: ignore
        pass
    preview_len = get_effective_preview_length(user_id)
    text, markup, page_used = build_list_message(
        posts, state.get("filter", "all"), state.get("page", 1), state.get("query"), preview_len, context, user_id
    )
    state["page"] = page_used  # sync clamped page back to state
    set_list_state(context, state)
    await query.edit_message_text(
        text, reply_markup=markup, disable_web_page_preview=True, parse_mode="MarkdownV2"
    )


async def toggle_publish_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    api_key = users_data[user_id].api_key
    tok = query.data.split(":", 1)[1]
    slug = resolve_token_to_slug(context, user_id, tok)
    if not slug or not is_valid_slug(slug):
        await query.edit_message_text(stale_action_text())
        return
    # Determine current status
    chat_id = safe_chat_id(query=query)
    if chat_id is not None:
        await send_typing(context, chat_id)
    response, data = await api_call("GET", api_key, slug=slug, context=context, chat_id=chat_id)
    ok_shape = isinstance(data, dict) and ("title" in data or "body" in data or "slug" in data)
    if not ((http_2xx(response) and ok_shape) or payload_ok(data)):
        await query.edit_message_text(with_status(MESSAGES["FAILED_FETCH_FOR_TOGGLE"], response))
        return
    is_pub = bool(data.get("published_at")) if isinstance(data, dict) else False
    payload = {"published_at": None if is_pub else now_date_str()}

    # Save for retry
    users_data[user_id].last_action = {"type": "togglepub", "slug": slug, "payload": payload}
    await save_users_data()

    response2, data2 = await api_call(
        "PATCH", api_key, slug=slug, payload=payload, context=context, chat_id=chat_id
    )
    if http_2xx(response2) or payload_ok(data2):
        # Refresh list view inline without tripping cooldown
        context.user_data.pop(K_POSTS_CACHE, None)
        state = get_list_state(context)
        posts, _ = await fetch_posts_for_user(user_id, context, chat_id=chat_id)
        if posts is not None:
            preview_len = get_effective_preview_length(user_id)
            text, markup, page_used = build_list_message(
                posts, state.get("filter", "all"), state.get("page", 1), state.get("query"), preview_len, context, user_id
            )
            state["page"] = page_used
            set_list_state(context, state)
            await query.edit_message_text(
                text, reply_markup=markup, disable_web_page_preview=True, parse_mode="MarkdownV2"
            )
        else:
            try:
                await query.edit_message_text(MESSAGES["TOGGLED_PUBLISH_STATE"])
            except Exception:
                pass
        # Clear last action
        try:
            users_data[user_id].last_action = {}
            await save_users_data()
        except Exception:
            pass
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(MESSAGES["BUTTON_RETRY"], callback_data=CB_RETRY_TOGGLEPUB)]]
        )
        try:
            await query.edit_message_text(
                with_status(MESSAGES["FAILED_TOGGLE_PUBLISH"], response2), reply_markup=keyboard
            )
        except Exception:
            pass
