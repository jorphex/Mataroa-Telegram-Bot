# ruff: noqa: F403, F405

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from constants import *
from handler_ui import cancel_keyboard
from handler_utils import ensure_allowed, schedule_users_data_save, send_or_edit
from storage import UserData, users_data

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat and chat.type != "private":
        await update.message.reply_text(MESSAGES["SET_API_PRIVATE"])
        return ConversationHandler.END
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        MESSAGES["START_WELCOME"],
        reply_markup=cancel_keyboard(),
    )
    return ENTER_API_KEY


async def enter_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat and chat.type != "private":
        await update.message.reply_text(MESSAGES["SET_API_PRIVATE"])
        return ConversationHandler.END
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    user_id = update.message.from_user.id
    api_key = update.message.text.strip()
    users_data[user_id] = users_data.get(user_id, UserData(api_key=api_key))
    users_data[user_id].api_key = api_key
    await schedule_users_data_save(context)
    await update.message.reply_text(MESSAGES["API_SAVED"])
    return ConversationHandler.END


# /help: Show help information
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return
    await send_or_edit(MESSAGES["HELP_TEXT"], update=update)


# Global cancel handler (for messages & inline keyboards)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_allowed(update, context):
        return ConversationHandler.END
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        await send_or_edit(MESSAGES["OP_CANCELLED"], update=update, query=update.callback_query)
    else:
        await update.message.reply_text(MESSAGES["OP_CANCELLED"])
    return ConversationHandler.END
