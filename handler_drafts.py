# ruff: noqa: F403, F405

from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from constants import *
from handler_ui import (
    build_drafts_message,
    cancel_keyboard,
    drafting_keyboard,
    publish_choice_keyboard,
    render_create_preview,
    render_create_preview_plain,
)
from handler_state import (
    _active_draft_data,
    _clear_active_draft,
    _drafts_map,
    _has_active_draft,
    _save_draft_snapshot,
    _set_active_draft,
    gate_callback,
    get_draft_parts,
    set_draft_parts,
)
from handler_utils import (
    ensure_allowed,
    ensure_api_key_or_prompt,
    ensure_private,
    extract_message_text,
    get_preview_format,
    schedule_users_data_save,
    stale_action_text,
)
from storage import users_data

async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return ConversationHandler.END

    # Resume last draft if exists
    u = users_data[user_id]
    set_draft_parts(context, list(u.draft_parts) if u.draft_parts else [])
    context.user_data[K_UNDO_STACK] = list(u.undo_stack) if u.undo_stack else []
    if u.draft_title:
        context.user_data[K_TITLE] = u.draft_title
        await update.message.reply_text(
            MESSAGES["RESUME_DRAFT"].format(title=u.draft_title),
            reply_markup=drafting_keyboard(),
        )
        return ENTER_BODY

    await update.message.reply_text(MESSAGES["ENTER_TITLE_PROMPT"], reply_markup=cancel_keyboard())
    return ENTER_TITLE


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fast path: /new Title | Body
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return ConversationHandler.END

    text = update.message.text or ""
    parts = text.split(" ", 1)
    arg = parts[1] if len(parts) > 1 else ""
    title = ""
    body = ""
    if "|" in arg:
        t, b = arg.split("|", 1)
        title = t.strip()
        body = b.strip()
    else:
        title = arg.strip()
    if title:
        context.user_data[K_TITLE] = title
        users_data[user_id].draft_title = title
        await schedule_users_data_save(context)
        if body:
            # Direct to publish choice
            set_draft_parts(context, [body])
            context.user_data[K_UNDO_STACK] = [body]
            context.user_data[K_BODY] = body
            users_data[user_id].draft_parts = [body]
            users_data[user_id].undo_stack = [body]
            await schedule_users_data_save(context)
            default_mode = users_data[user_id].settings.get("default_publish_mode", "draft")
            await update.message.reply_text(
                MESSAGES["CHOOSE_PUBLICATION_OPTION"],
                reply_markup=publish_choice_keyboard(default_mode=default_mode),
            )
            return ENTER_PUBLISH_CHOICE
        else:
            await update.message.reply_text(
                MESSAGES["NOW_SEND_BODY"],
                reply_markup=drafting_keyboard(),
            )
            return ENTER_BODY
    else:
        # Fallback to normal /post flow
        return await post(update, context)


async def enter_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_TITLE
    title = extract_message_text(update.message).strip()
    if not title:
        await update.message.reply_text(MESSAGES["PROMPT_VALID_TITLE"], reply_markup=cancel_keyboard())
        return ENTER_TITLE
    context.user_data[K_TITLE] = title
    # Persist as draft title for resume
    u = users_data[update.message.from_user.id]
    u.draft_title = title
    await schedule_users_data_save(context)
    await update.message.reply_text(
        MESSAGES["SEND_BODY_MULTIMSG"],
        reply_markup=drafting_keyboard(),
    )
    return ENTER_BODY


async def enter_body(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    text = extract_message_text(update.message)
    if not text.strip():
        await update.message.reply_text(MESSAGES["PROMPT_VALID_CONTENT"], reply_markup=drafting_keyboard())
        return ENTER_BODY
    parts = get_draft_parts(context)
    parts.append(text)
    set_draft_parts(context, parts)
    # Maintain undo stack
    undo_stack = context.user_data.get(K_UNDO_STACK, [])
    undo_stack.append(text)
    context.user_data[K_UNDO_STACK] = undo_stack

    # Persist draft to users_data for resume
    u = users_data[update.message.from_user.id]
    u.draft_parts = list(parts)
    u.undo_stack = list(undo_stack)
    await schedule_users_data_save(context)

    await update.message.reply_text(MESSAGES["ADDED_TO_DRAFT"], reply_markup=drafting_keyboard())
    return ENTER_BODY


async def draft_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    parts = get_draft_parts(context)
    title = context.user_data.get(K_TITLE, "(no title)")
    body = "\n".join(parts)
    user_id = update.message.from_user.id
    fmt = get_preview_format(user_id)
    preview = (
        render_create_preview_plain(title, body, None)
        if fmt == "plain"
        else render_create_preview(title, body, None)
    )
    parse_mode = "MarkdownV2" if fmt == "markdown" else None
    await update.message.reply_text(
        preview, parse_mode=parse_mode, reply_markup=drafting_keyboard()
    )
    return ENTER_BODY


async def draft_preview_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    if not await ensure_private(update, context):
        return ENTER_BODY
    if not await gate_callback(query, context):
        return ENTER_BODY
    parts = get_draft_parts(context)
    title = context.user_data.get(K_TITLE, "(no title)")
    body = "\n".join(parts)
    user_id = query.from_user.id
    fmt = get_preview_format(user_id)
    preview = (
        render_create_preview_plain(title, body, None)
        if fmt == "plain"
        else render_create_preview(title, body, None)
    )
    parse_mode = "MarkdownV2" if fmt == "markdown" else None
    await query.edit_message_text(preview, parse_mode=parse_mode, reply_markup=drafting_keyboard())
    return ENTER_BODY


async def draft_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    _clear_active_draft(update.message.from_user.id, context)
    await schedule_users_data_save(context)
    await update.message.reply_text(
        f"{MESSAGES['DRAFT_CLEARED']}\n\n{MESSAGES['ENTER_TITLE_PROMPT']}",
        reply_markup=cancel_keyboard(),
    )
    return ENTER_TITLE


async def draft_clear_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    if not await ensure_private(update, context):
        return ENTER_BODY
    if not await gate_callback(query, context):
        return ENTER_BODY
    _clear_active_draft(query.from_user.id, context)
    await schedule_users_data_save(context)
    await query.edit_message_text(
        f"{MESSAGES['DRAFT_CLEARED']}\n\n{MESSAGES['ENTER_TITLE_PROMPT']}",
        reply_markup=cancel_keyboard(),
    )
    return ENTER_TITLE


async def draft_undo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    if not await ensure_private(update, context):
        return ENTER_BODY
    if not await gate_callback(query, context):
        return ENTER_BODY
    undo_stack = context.user_data.get(K_UNDO_STACK, [])
    if undo_stack:
        last = undo_stack.pop()
        parts = get_draft_parts(context)
        if parts and parts[-1] == last:
            parts.pop()
        context.user_data[K_UNDO_STACK] = undo_stack
        set_draft_parts(context, parts)
        u = users_data[query.from_user.id]
        u.draft_parts = list(parts)
        u.undo_stack = list(undo_stack)
        await schedule_users_data_save(context)
        await query.edit_message_text(MESSAGES["REMOVED_LAST_CHUNK"], reply_markup=drafting_keyboard())
    else:
        await query.edit_message_text(MESSAGES["NOTHING_TO_UNDO"], reply_markup=drafting_keyboard())
    return ENTER_BODY


async def _save_current_draft(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    title, parts = _active_draft_data(user_id, context)
    draft_id = _save_draft_snapshot(user_id, title, parts)
    if not draft_id:
        return None
    await schedule_users_data_save(context)
    return _drafts_map(user_id).get(draft_id, {}).get("title") or _draft_title_for_save(title, parts)


async def draft_save_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    if not await ensure_private(update, context):
        return ENTER_BODY
    if not await gate_callback(query, context):
        return ENTER_BODY
    user_id = query.from_user.id
    title = await _save_current_draft(user_id, context)
    if not title:
        await query.edit_message_text(MESSAGES["DRAFT_EMPTY"], reply_markup=drafting_keyboard())
        return ENTER_BODY
    await query.edit_message_text(
        MESSAGES["DRAFT_SAVED_AS"].format(title=title), reply_markup=drafting_keyboard()
    )
    return ENTER_BODY


async def save_draft_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    title = await _save_current_draft(user_id, context)
    if not title:
        await update.message.reply_text(MESSAGES["DRAFT_EMPTY"])
        return
    await update.message.reply_text(MESSAGES["DRAFT_SAVED_AS"].format(title=title))


async def drafts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    if not await ensure_private(update, context):
        return
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return
    text, markup = build_drafts_message(user_id)
    await update.message.reply_text(text, reply_markup=markup)


async def _render_drafts_list(query: Any, user_id: int) -> None:
    text, markup = build_drafts_message(user_id)
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except Exception:
        pass


async def drafts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    data = query.data or ""
    drafts = _drafts_map(user_id)
    if data.startswith(CB_DRAFT_OPEN_PREFIX):
        draft_id = data[len(CB_DRAFT_OPEN_PREFIX):]
        dval = drafts.get(draft_id)
        if not dval:
            await query.edit_message_text(stale_action_text())
            return
        title, parts = _active_draft_data(user_id, context)
        if _has_active_draft(title, parts):
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            MESSAGES["BUTTON_DRAFT_REPLACE"],
                            callback_data=f"{CB_DRAFT_REPLACE_PREFIX}{draft_id}",
                        ),
                        InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_DRAFT_BACK),
                    ]
                ]
            )
            await query.edit_message_text(
                MESSAGES["DRAFT_REPLACE_CONFIRM"].format(title=dval.get("title", "")),
                reply_markup=keyboard,
            )
            return
        _set_active_draft(user_id, context, dval.get("title", ""), dval.get("parts", []))
        await schedule_users_data_save(context)
        try:
            await query.answer(MESSAGES["DRAFT_LOADED"].split("\n", 1)[0], show_alert=False)
        except Exception:
            pass
        await _render_drafts_list(query, user_id)
    elif data.startswith(CB_DRAFT_REPLACE_PREFIX):
        draft_id = data[len(CB_DRAFT_REPLACE_PREFIX):]
        dval = drafts.get(draft_id)
        if not dval:
            await query.edit_message_text(stale_action_text())
            return
        _set_active_draft(user_id, context, dval.get("title", ""), dval.get("parts", []))
        await schedule_users_data_save(context)
        try:
            await query.answer(MESSAGES["DRAFT_LOADED"].split("\n", 1)[0], show_alert=False)
        except Exception:
            pass
        await _render_drafts_list(query, user_id)
    elif data.startswith(CB_DRAFT_DELETE_PREFIX):
        draft_id = data[len(CB_DRAFT_DELETE_PREFIX):]
        dval = drafts.pop(draft_id, None)
        await schedule_users_data_save(context)
        try:
            await query.answer(MESSAGES["DRAFT_DELETED"].format(title=(dval or {}).get("title", "")))
        except Exception:
            pass
        await _render_drafts_list(query, user_id)
    elif data == CB_DRAFT_BACK:
        await _render_drafts_list(query, user_id)

async def draft_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    parts = get_draft_parts(context)
    if not parts:
        await update.message.reply_text(MESSAGES["DRAFT_EMPTY"], reply_markup=drafting_keyboard())
        return ENTER_BODY
    context.user_data[K_BODY] = "\n".join(parts)
    user_id = update.message.from_user.id
    default_mode = users_data[user_id].settings.get("default_publish_mode", "draft")
    await update.message.reply_text(
        MESSAGES["CHOOSE_PUBLICATION_OPTION"],
        reply_markup=publish_choice_keyboard(default_mode=default_mode),
    )
    return ENTER_PUBLISH_CHOICE


async def draft_done_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return ENTER_BODY
    parts = get_draft_parts(context)
    if not parts:
        await query.edit_message_text(MESSAGES["DRAFT_EMPTY"], reply_markup=drafting_keyboard())
        return ENTER_BODY
    context.user_data[K_BODY] = "\n".join(parts)
    user_id = query.from_user.id
    default_mode = users_data[user_id].settings.get("default_publish_mode", "draft")
    await query.edit_message_text(
        MESSAGES["CHOOSE_PUBLICATION_OPTION"],
        reply_markup=publish_choice_keyboard(default_mode=default_mode),
    )
    return ENTER_PUBLISH_CHOICE


async def template_insert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ENTER_BODY
    if not await ensure_private(update, context):
        return ENTER_BODY
    if not await gate_callback(query, context):
        return ENTER_BODY
    _, key = query.data.split(":", 1)
    tpl = TEMPLATES.get(key)
    if tpl:
        parts = get_draft_parts(context)
        parts.append(tpl)
        set_draft_parts(context, parts)
        undo_stack = context.user_data.get(K_UNDO_STACK, [])
        undo_stack.append(tpl)
        context.user_data[K_UNDO_STACK] = undo_stack
        # Persist
        u = users_data[query.from_user.id]
        u.draft_parts = list(parts)
        u.undo_stack = list(undo_stack)
        await schedule_users_data_save(context)
        await query.edit_message_text(
            f"📎 Inserted template '{key}'.", reply_markup=drafting_keyboard()
        )
    else:
        await query.edit_message_text("Template not found.", reply_markup=drafting_keyboard())
    return ENTER_BODY
