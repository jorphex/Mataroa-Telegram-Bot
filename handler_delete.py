# ruff: noqa: F403, F405

from contextlib import suppress
import logging
from typing import Any, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from constants import *
from handler_basic import cancel
from handler_state import _get_user_bucket, gate_callback, resolve_token_to_slug, token_for_slug
from handler_ui import cancel_keyboard
from handler_utils import (
    api_call,
    ensure_allowed,
    ensure_api_key_or_prompt,
    ensure_private,
    get_user_id,
    http_2xx,
    is_valid_slug,
    safe_chat_id,
    save_users_data,
    send_or_edit,
    stale_action_text,
    with_status,
)
from storage import users_data

logger = logging.getLogger(__name__)

def get_pending_deletes_map(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> Dict[str, Any]:
    """Ensure and return the application's per-user pending deletes map."""
    try:
        app_ud = context.application.user_data  # type: ignore[attr-defined]
    except Exception:
        app_ud = {}
    ud = app_ud.get(user_id)
    if ud is None:
        ud = {}
        app_ud[user_id] = ud
    pending = ud.get("pending_deletes")
    if pending is None:
        pending = {}
        ud["pending_deletes"] = pending
    return pending


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    user_id = await ensure_api_key_or_prompt(update, context)
    if not user_id:
        return ConversationHandler.END
    if context.args:
        slug_arg = context.args[0]
        if not is_valid_slug(slug_arg):
            await update.message.reply_text(MESSAGES["PROMPT_VALID_SLUG"])
            return ENTER_DELETE_SLUG
        context.user_data[K_SLUG] = slug_arg
        settings = users_data[user_id].settings
        if not settings.get("confirm_before_delete", True):
            await schedule_delete_with_undo_message(update.message, context, slug_arg)
            return ConversationHandler.END
        return await confirm_delete_prompt(update, context)
    await update.message.reply_text(
        "✏️ Enter the slug of the post you want to delete:", reply_markup=cancel_keyboard()
    )
    return ENTER_DELETE_SLUG


# New entry point for inline delete button.
async def inline_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    tok = query.data.split(CB_DELETE_PREFIX, 1)[1]
    slug = resolve_token_to_slug(context, user_id, tok)
    if not slug or not is_valid_slug(slug):
        await query.edit_message_text(stale_action_text())
        return ConversationHandler.END
    context.user_data[K_SLUG] = slug
    # If settings confirm-before-delete is False, schedule immediately with undo
    settings = users_data[user_id].settings
    if not settings.get("confirm_before_delete", True):
        await schedule_delete_with_undo(query, context, slug)
        return ConversationHandler.END
    return await confirm_delete_prompt(update, context)


async def enter_delete_slug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ENTER_DELETE_SLUG
    slug = update.message.text.strip()
    if not slug or not is_valid_slug(slug):
        await update.message.reply_text(MESSAGES["PROMPT_VALID_SLUG"], reply_markup=cancel_keyboard())
        return ENTER_DELETE_SLUG
    context.user_data[K_SLUG] = slug
    settings = users_data[update.message.from_user.id].settings
    if not settings.get("confirm_before_delete", True):
        await schedule_delete_with_undo_message(update.message, context, slug)
        return ConversationHandler.END
    return await confirm_delete_prompt(update, context)


async def confirm_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    slug = context.user_data.get(K_SLUG)
    token = token_for_slug(context, user_id, slug) if user_id and slug else ""
    confirm_cb = f"{CB_CONFIRM_DELETE}:{token}" if token else CB_CONFIRM_DELETE
    keyboard = [
        [
            InlineKeyboardButton(MESSAGES["BUTTON_YES_DELETE"], callback_data=confirm_cb),
            InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit(
        MESSAGES["CONFIRM_DELETE"].format(slug=context.user_data[K_SLUG]),
        reply_markup=reply_markup,
        update=update,
        query=update.callback_query if update.callback_query else None,
    )
    # Always move to confirm state so the confirm handler is active
    return CONFIRM_DELETE


async def schedule_delete_with_undo(query: Any, context: ContextTypes.DEFAULT_TYPE, slug: str) -> None:
    """Schedule a delete job with an inline Undo button within DELETE_GRACE_SEC seconds."""
    user_id = query.from_user.id
    api_key = users_data[user_id].api_key
    chat_id = safe_chat_id(query=query)
    msg_id = query.message.message_id if getattr(query, "message", None) else None

    # Save for retry (delete)
    users_data[user_id].last_action = {"type": "delete", "slug": slug}
    await save_users_data()

    pending = get_pending_deletes_map(context, user_id)
    # Prevent double-scheduling: cancel existing
    existing = pending.get(slug)
    if existing:
        try:
            existing.schedule_removal()
        except Exception:
            pass
    # schedule job
    job = context.job_queue.run_once(
        execute_delete_job,
        DELETE_GRACE_SEC,
        data={
            "user_id": user_id,
            "api_key": api_key,
            "slug": slug,
            "chat_id": chat_id,
            "message_id": msg_id,
        },
    )
    pending[slug] = job

    tok = token_for_slug(context, user_id, slug)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(MESSAGES["BUTTON_UNDO_DELETE"], callback_data=f"{CB_UNDO_DELETE_PREFIX}{tok}")]]
    )
    await query.edit_message_text(
        MESSAGES["DELETING_IN"].format(slug=slug, seconds=DELETE_GRACE_SEC), reply_markup=kb
    )


async def schedule_delete_with_undo_message(message: Any, context: ContextTypes.DEFAULT_TYPE, slug: str) -> None:
    """Schedule a delete job (message context) with Undo within DELETE_GRACE_SEC seconds."""
    user_id = message.from_user.id
    api_key = users_data[user_id].api_key

    # Save for retry (delete)
    users_data[user_id].last_action = {"type": "delete", "slug": slug}
    await save_users_data()

    pending = get_pending_deletes_map(context, user_id)
    existing = pending.get(slug)
    if existing:
        try:
            existing.schedule_removal()
        except Exception:
            pass

    tok = token_for_slug(context, user_id, slug)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(MESSAGES["BUTTON_UNDO_DELETE"], callback_data=f"{CB_UNDO_DELETE_PREFIX}{tok}")]]
    )
    sent = await message.reply_text(
        MESSAGES["DELETING_IN"].format(slug=slug, seconds=DELETE_GRACE_SEC), reply_markup=kb
    )

    job = context.job_queue.run_once(
        execute_delete_job,
        DELETE_GRACE_SEC,
        data={
            "user_id": user_id,
            "api_key": api_key,
            "slug": slug,
            "chat_id": sent.chat_id,
            "message_id": sent.message_id,
        },
    )
    pending[slug] = job


def delete_retry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(MESSAGES["BUTTON_RETRY"], callback_data=CB_RETRY_DELETE)]]
    )


async def clear_matching_delete_retry(user_id: int, slug: str) -> None:
    user = users_data.get(user_id)
    if (
        user
        and user.last_action.get("type") == "delete"
        and user.last_action.get("slug") == slug
    ):
        user.last_action = {}
        await save_users_data()


async def notify_delete_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: Optional[int],
    message_id: Optional[int],
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    if chat_id is None:
        return
    if message_id is not None:
        try:
            await context.application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    with suppress(Exception):
        await context.application.bot.send_message(
            chat_id, text=text, reply_markup=reply_markup
        )


async def execute_delete_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the actual delete call after the grace period and edit the pending message."""
    data = context.job.data
    user_id = data["user_id"]
    api_key = data["api_key"]
    slug = data["slug"]
    chat_id = data["chat_id"]
    message_id = data.get("message_id")

    with suppress(Exception):
        get_pending_deletes_map(context, user_id).pop(slug, None)

    try:
        response, _ = await api_call("DELETE", api_key, slug=slug)
    except Exception:
        logger.exception("Delete job failed")
        await notify_delete_result(
            context,
            chat_id,
            message_id,
            MESSAGES["FAILED_DELETE_POST_FMT"].format(slug=slug),
            reply_markup=delete_retry_keyboard(),
        )
        return

    if http_2xx(response):
        await clear_matching_delete_retry(user_id, slug)
        with suppress(Exception):
            _get_user_bucket(context, user_id).pop(K_POSTS_CACHE, None)
        await notify_delete_result(
            context,
            chat_id,
            message_id,
            MESSAGES["POST_DELETED"].format(slug=slug),
        )
        return

    await notify_delete_result(
        context,
        chat_id,
        message_id,
        with_status(MESSAGES["FAILED_DELETE_POST_FMT"].format(slug=slug), response),
        reply_markup=delete_retry_keyboard(),
    )


async def undo_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Undo action for a scheduled deletion if still pending."""
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return ConversationHandler.END
    tok = query.data.split(":", 1)[1]
    user_id = query.from_user.id
    slug = resolve_token_to_slug(context, user_id, tok)
    if not slug:
        try:
            await query.edit_message_text(stale_action_text())
        except Exception:
            pass
        return ConversationHandler.END
    pending = get_pending_deletes_map(context, user_id)
    job = pending.get(slug)
    if job and getattr(job, "enabled", True):
        try:
            job.schedule_removal()
        except Exception:
            pass
        pending.pop(slug, None)
        try:
            await query.edit_message_text(MESSAGES["UNDO_DELETE_CANCELLED"].format(slug=slug))
        except Exception:
            pass
    else:
        pending.pop(slug, None)
        try:
            await query.edit_message_text(MESSAGES["TOO_LATE_UNDO"])
        except Exception:
            pass


async def confirm_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if not await ensure_private(update, context):
        return ConversationHandler.END
    if not await gate_callback(query, context):
        return CONFIRM_DELETE
    if query.data == CB_CANCEL:
        return await cancel(update, context)
    if not query.data.startswith(CB_CONFIRM_DELETE):
        await query.answer(MESSAGES["INVALID_OR_STALE_ACTION"])  # best effort
        return CONFIRM_DELETE
    user_id = query.from_user.id
    tok = query.data.split(":", 1)[1] if ":" in query.data else ""
    slug = resolve_token_to_slug(context, user_id, tok) if tok else None
    if not slug or not is_valid_slug(slug):
        await query.edit_message_text(stale_action_text())
        return ConversationHandler.END
    await schedule_delete_with_undo(query, context, slug)
    return ConversationHandler.END
