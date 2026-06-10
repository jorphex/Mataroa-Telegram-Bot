# ruff: noqa: F403, F405

from typing import Any, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from constants import *
from handler_basic import cancel
from handler_state import _clear_active_draft, gate_callback, resolve_token_to_slug, token_for_slug
from handler_ui import (
    cancel_keyboard,
    open_url_button,
    preview_submit_keyboard,
    publish_choice_keyboard,
    render_create_preview,
    render_create_preview_plain,
    render_update_preview,
    render_update_preview_plain,
    update_preview_submit_keyboard,
)
from handler_utils import (
    api_call,
    ensure_allowed,
    ensure_api_key_or_prompt,
    ensure_private,
    extract_message_text,
    http_2xx,
    is_valid_absolute_url,
    is_valid_slug,
    mdv2,
    now_date_str,
    payload_ok,
    safe_chat_id,
    save_users_data,
    slugify,
    stale_action_text,
    truncate,
    with_status,
)
from storage import users_data

async def post_publish_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return ENTER_PUBLISH_CHOICE
    if query.data == CB_CANCEL:
        return await cancel(update, context)
    if query.data not in (CB_CHOICE_DRAFT, CB_CHOICE_PUBLISH):
        await query.answer(MESSAGES["INVALID_ACTION"])  # best effort
        return ENTER_PUBLISH_CHOICE
    choice = query.data
    published_at = None if choice == CB_CHOICE_DRAFT else now_date_str()
    context.user_data[K_PUBLISHED_AT] = published_at
    # Show preview with confirmation options
    user_id = query.from_user.id
    fmt = get_preview_format(user_id)
    preview = (
        render_create_preview_plain(context.user_data[K_TITLE], context.user_data[K_BODY], published_at)
        if fmt == "plain"
        else render_create_preview(context.user_data[K_TITLE], context.user_data[K_BODY], published_at)
    )
    reply_markup = preview_submit_keyboard(include_slug_sync=False)
    parse_mode = "MarkdownV2" if fmt == "markdown" else None
    await query.edit_message_text(preview, parse_mode=parse_mode, reply_markup=reply_markup)
    return CONFIRM_POST


async def _submit_create_post(query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit a create-post request based on context state and render outcome in place."""
    user_id = query.from_user.id
    api_key = users_data[user_id].api_key
    payload = {
        "title": context.user_data[K_TITLE],
        "body": context.user_data[K_BODY],
        "published_at": context.user_data.get(K_PUBLISHED_AT),
    }
    # Save for retry
    users_data[user_id].last_action = {"type": "create", "payload": payload}
    await save_users_data()

    chat_id = safe_chat_id(query=query)
    response, data = await api_call(
        "POST", api_key, payload=payload, context=context, chat_id=chat_id
    )
    success = http_2xx(response) or payload_ok(data)
    if success:
        slug = data.get("slug") if isinstance(data, dict) else None
        url = data.get("url") if isinstance(data, dict) else None
        # Clear draft after success
        _clear_active_draft(user_id, context)
        users_data[user_id].last_action = {}
        await save_users_data()
        context.user_data.pop(K_POSTS_CACHE, None)
        # Add inline buttons for immediate Edit and Delete actions.
        rows: List[List[InlineKeyboardButton]] = []
        if slug:
            tok = token_for_slug(context, user_id, slug)
            rows.append(
                [
                    InlineKeyboardButton(MESSAGES["BUTTON_EDIT"], callback_data=f"{CB_EDIT_PREFIX}{tok}"),
                    InlineKeyboardButton(MESSAGES["BUTTON_DELETE"], callback_data=f"{CB_DELETE_PREFIX}{tok}"),
                ]
            )
        if is_valid_absolute_url(url or ""):
            rows.append([open_url_button(url)])
        keyboard = InlineKeyboardMarkup(rows) if rows else None
        published_status = "Published" if context.user_data.get(K_PUBLISHED_AT) else "Draft"
        if slug or url:
            await query.edit_message_text(
                MESSAGES["POST_CREATED_WITH_DETAILS"].format(slug=slug, status=published_status, url=url),
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(MESSAGES["POST_CREATED"], disable_web_page_preview=True)
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(MESSAGES["BUTTON_RETRY"], callback_data=CB_RETRY_CREATE)]]
        )
        await query.edit_message_text(
            with_status(MESSAGES["FAILED_CREATE_POST"], response), reply_markup=keyboard
        )


async def confirm_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return CONFIRM_POST
    if query.data == CB_CANCEL:
        return await cancel(update, context)
    if query.data != CB_SUBMIT_POST:
        await query.answer(MESSAGES["INVALID_OR_STALE_ACTION"])  # best effort
        return CONFIRM_POST
    await _submit_create_post(query, context)
    return ConversationHandler.END


# ----- Update Post Flow -----
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return ConversationHandler.END
    await update.message.reply_text(
        MESSAGES["ENTER_UPDATE_SLUG_PROMPT"], reply_markup=cancel_keyboard()
    )
    return ENTER_UPDATE_SLUG


# New entry point for inline edit button.
async def inline_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return ConversationHandler.END
    # Ensure API key configured
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return ConversationHandler.END
    tok = query.data.split(CB_EDIT_PREFIX, 1)[1]
    slug = resolve_token_to_slug(context, user_id, tok)
    if not slug or not is_valid_slug(slug):
        await query.edit_message_text(stale_action_text())
        return ConversationHandler.END
    context.user_data[K_SLUG] = slug
    api_key = users_data[user_id].api_key
    chat_id = safe_chat_id(query=query)
    response, res_data = await api_call(
        "GET", api_key, slug=slug, context=context, chat_id=chat_id
    )
    ok_shape = isinstance(res_data, dict) and (
        "title" in res_data or "body" in res_data or "slug" in res_data
    )
    if ((http_2xx(response) and ok_shape) or payload_ok(res_data)):
        current_title = res_data.get("title", "N/A") if isinstance(res_data, dict) else "N/A"
        current_body = res_data.get("body", "N/A") if isinstance(res_data, dict) else "N/A"
        context.user_data[K_CURRENT_SLUG] = slug
        context.user_data[K_CURRENT_TITLE] = current_title
        context.user_data[K_CURRENT_BODY] = current_body
        context.user_data[K_SLUG_SYNC] = False
        message = (
            f"*{mdv2(MESSAGES['CURRENT_TITLE_LABEL'])}:*\n{mdv2(current_title)}\n\n"
            f"*{mdv2(MESSAGES['CURRENT_BODY_LABEL'])}:*\n{mdv2(truncate(current_body, 500))}\n\n"
            f"{mdv2(MESSAGES['ENTER_UPDATED_TITLE'])}"
        )
        await query.edit_message_text(message, parse_mode="MarkdownV2", reply_markup=cancel_keyboard())
        return ENTER_UPDATED_TITLE
    else:
        await query.edit_message_text(with_status(MESSAGES["FAILED_FETCH_POST_DETAILS"], response))
        return ConversationHandler.END


async def enter_update_slug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_UPDATE_SLUG
    slug = update.message.text.strip()
    if not slug or not is_valid_slug(slug):
        await update.message.reply_text(MESSAGES["PROMPT_VALID_SLUG"], reply_markup=cancel_keyboard())
        return ENTER_UPDATE_SLUG
    context.user_data[K_SLUG] = slug
    user_id = update.message.from_user.id
    api_key = users_data[user_id].api_key
    response, data = await api_call(
        "GET", api_key, slug=slug, context=context, chat_id=safe_chat_id(update)
    )
    ok_shape = isinstance(data, dict) and ("title" in data or "body" in data or "slug" in data)
    if ((http_2xx(response) and ok_shape) or payload_ok(data)):
        current_title = data.get("title", "N/A") if isinstance(data, dict) else "N/A"
        current_body = data.get("body", "N/A") if isinstance(data, dict) else "N/A"
        context.user_data[K_CURRENT_SLUG] = slug
        context.user_data[K_CURRENT_TITLE] = current_title
        context.user_data[K_CURRENT_BODY] = current_body
        context.user_data[K_SLUG_SYNC] = False
        message = (
            f"*{mdv2(MESSAGES['CURRENT_TITLE_LABEL'])}:*\n{mdv2(current_title)}\n\n"
            f"*{mdv2(MESSAGES['CURRENT_BODY_LABEL'])}:*\n{mdv2(truncate(current_body, 500))}\n\n"
            f"{mdv2(MESSAGES['ENTER_UPDATED_TITLE'])}"
        )
        await update.message.reply_text(
            message, parse_mode="MarkdownV2", reply_markup=cancel_keyboard()
        )
        return ENTER_UPDATED_TITLE
    else:
        await update.message.reply_text(
            with_status(MESSAGES["FAILED_FETCH_POST_DETAILS_CHECK"], response)
        )
        return ConversationHandler.END


async def enter_updated_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_UPDATED_TITLE
    updated_title = extract_message_text(update.message).strip()
    if not updated_title:
        await update.message.reply_text(MESSAGES["PROMPT_VALID_TITLE"], reply_markup=cancel_keyboard())
        return ENTER_UPDATED_TITLE
    context.user_data[K_TITLE] = updated_title
    # Slug sync suggestion
    current_slug = context.user_data.get(K_CURRENT_SLUG, context.user_data.get(K_SLUG))
    suggested = slugify(updated_title)
    context.user_data[K_SLUG_SUGGESTED] = suggested
    context.user_data[K_SLUG_SUGGESTED_VALID] = bool(suggested) and is_valid_slug(suggested)
    note = ""
    if current_slug and context.user_data[K_SLUG_SUGGESTED_VALID] and current_slug != suggested:
        note = MESSAGES["SLUG_SUGGESTION_NOTE_MD"].format(current=mdv2(current_slug), suggested=mdv2(suggested))
    msg = mdv2(MESSAGES["ENTER_UPDATED_BODY"]) + note
    await update.message.reply_text(msg, reply_markup=cancel_keyboard(), parse_mode="MarkdownV2")
    return ENTER_UPDATED_BODY


async def enter_updated_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_UPDATED_BODY
    updated_body = extract_message_text(update.message)
    if not updated_body.strip():
        await update.message.reply_text(MESSAGES["PROMPT_VALID_CONTENT"], reply_markup=cancel_keyboard())
        return ENTER_UPDATED_BODY
    context.user_data[K_BODY] = updated_body
    user_id = update.message.from_user.id
    default_mode = users_data[user_id].settings.get("default_publish_mode", "draft")
    await update.message.reply_text(
        MESSAGES["CHOOSE_PUBLICATION_OPTION"],
        reply_markup=publish_choice_keyboard(default_mode=default_mode),
    )
    return ENTER_PUBLISH_CHOICE_UPDATE


async def update_publish_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return ENTER_PUBLISH_CHOICE_UPDATE
    if query.data == CB_CANCEL:
        return await cancel(update, context)
    if query.data not in (CB_CHOICE_DRAFT, CB_CHOICE_PUBLISH):
        await query.answer(MESSAGES["INVALID_ACTION"])  # best effort
        return ENTER_PUBLISH_CHOICE_UPDATE
    choice = query.data
    published_at = None if choice == CB_CHOICE_DRAFT else now_date_str()
    context.user_data[K_PUBLISHED_AT] = published_at
    current_slug = context.user_data.get(K_CURRENT_SLUG, context.user_data.get(K_SLUG))
    suggested = context.user_data.get(K_SLUG_SUGGESTED, current_slug)
    valid_suggested = bool(suggested) and is_valid_slug(suggested) and suggested != current_slug
    slug_sync = context.user_data.get(K_SLUG_SYNC, False) if valid_suggested else False
    context.user_data[K_SLUG_SYNC] = slug_sync
    final_slug = suggested if slug_sync else current_slug
    preview = render_update_preview(
        context.user_data[K_TITLE],
        context.user_data[K_BODY],
        published_at,
        current_slug,
        suggested if valid_suggested else current_slug,
        slug_sync,
    )
    user_id = query.from_user.id
    fmt = get_preview_format(user_id)
    if fmt == "plain":
        preview = render_update_preview_plain(
            context.user_data[K_TITLE],
            context.user_data[K_BODY],
            published_at,
            current_slug,
            suggested if valid_suggested else current_slug,
            slug_sync,
        )
    reply_markup = update_preview_submit_keyboard(include_slug_sync=valid_suggested)
    parse_mode = "MarkdownV2" if fmt == "markdown" else None
    await query.edit_message_text(preview, parse_mode=parse_mode, reply_markup=reply_markup)
    context.user_data[K_FINAL_SLUG] = final_slug
    return CONFIRM_UPDATE


async def toggle_slug_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return CONFIRM_UPDATE
    if not await ensure_private(update, context):
        return CONFIRM_UPDATE
    if not await gate_callback(query, context):
        return CONFIRM_UPDATE
    current_slug = context.user_data.get(K_CURRENT_SLUG, context.user_data.get(K_SLUG))
    suggested = context.user_data.get(K_SLUG_SUGGESTED, current_slug)
    if not suggested or not is_valid_slug(suggested) or suggested == current_slug:
        await query.answer(MESSAGES["SLUG_SUGGESTION_UNAVAILABLE"], show_alert=True)
        return CONFIRM_UPDATE
    context.user_data[K_SLUG_SYNC] = not context.user_data.get(K_SLUG_SYNC, False)
    # Re-render preview
    slug_sync = context.user_data.get(K_SLUG_SYNC, False)
    published_at = context.user_data.get(K_PUBLISHED_AT)
    preview = render_update_preview(
        context.user_data[K_TITLE],
        context.user_data[K_BODY],
        published_at,
        current_slug,
        suggested,
        slug_sync,
    )
    user_id = query.from_user.id
    fmt = get_preview_format(user_id)
    if fmt == "plain":
        preview = render_update_preview_plain(
            context.user_data[K_TITLE],
            context.user_data[K_BODY],
            published_at,
            current_slug,
            suggested,
            slug_sync,
        )
    reply_markup = update_preview_submit_keyboard(include_slug_sync=True)
    parse_mode = "MarkdownV2" if fmt == "markdown" else None
    await query.edit_message_text(preview, parse_mode=parse_mode, reply_markup=reply_markup)
    context.user_data[K_FINAL_SLUG] = suggested if slug_sync else current_slug
    return CONFIRM_UPDATE


async def _submit_update_post(query: Any, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submit an update-post request based on context state and render outcome in place."""
    user_id = query.from_user.id
    api_key = users_data[user_id].api_key
    slug = context.user_data.get(K_CURRENT_SLUG, context.user_data.get(K_SLUG))
    payload = {
        "title": context.user_data[K_TITLE],
        "body": context.user_data[K_BODY],
        "published_at": context.user_data.get(K_PUBLISHED_AT),
    }
    final_slug = context.user_data.get(K_FINAL_SLUG, slug)
    if not is_valid_slug(final_slug or ""):
        final_slug = slug
    if final_slug and final_slug != slug:
        payload["slug"] = final_slug

    # Save for retry
    users_data[user_id].last_action = {"type": "update", "slug": slug, "payload": payload}
    await save_users_data()

    chat_id = safe_chat_id(query=query)
    response, data = await api_call(
        "PATCH", api_key, slug=slug, payload=payload, context=context, chat_id=chat_id
    )
    success = http_2xx(response) or payload_ok(data)
    if success:
        context.user_data.pop(K_POSTS_CACHE, None)
        url = data.get("url") if isinstance(data, dict) else None
        new_slug = data.get("slug", final_slug) if isinstance(data, dict) else final_slug
        rows: List[List[InlineKeyboardButton]] = []
        if new_slug:
            tok = token_for_slug(context, user_id, new_slug)
            rows.append(
                [
                    InlineKeyboardButton(MESSAGES["BUTTON_EDIT"], callback_data=f"{CB_EDIT_PREFIX}{tok}"),
                    InlineKeyboardButton(MESSAGES["BUTTON_DELETE"], callback_data=f"{CB_DELETE_PREFIX}{tok}"),
                ]
            )
        if is_valid_absolute_url(url or ""):
            rows.append([open_url_button(url)])
        keyboard = InlineKeyboardMarkup(rows) if rows else None
        try:
            await query.edit_message_text(
                MESSAGES["POST_UPDATED_WITH_DETAILS"].format(slug=new_slug, url=url), reply_markup=keyboard, disable_web_page_preview=True
            )
        except Exception:
            pass
        # Clear last action on success
        try:
            users_data[user_id].last_action = {}
            await save_users_data()
        except Exception:
            pass
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(MESSAGES["BUTTON_RETRY"], callback_data=CB_RETRY_UPDATE)]]
        )
        await query.edit_message_text(
            with_status(MESSAGES["FAILED_UPDATE_POST"], response), reply_markup=keyboard
        )


async def confirm_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return CONFIRM_UPDATE
    if query.data == CB_CANCEL:
        return await cancel(update, context)
    if query.data != CB_SUBMIT_UPDATE:
        await query.answer(MESSAGES["INVALID_OR_STALE_ACTION"])  # best effort
        return CONFIRM_UPDATE
    await _submit_update_post(query, context)
    return ConversationHandler.END
