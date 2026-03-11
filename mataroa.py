import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import handlers as h
from constants import (
    CB_CANCEL,
    CB_CHOICE_DRAFT,
    CB_CHOICE_PUBLISH,
    CB_CONFIRM_DELETE,
    CB_DELETE_PREFIX,
    CB_DRAFT_CLEAR,
    CB_DRAFT_DONE,
    CB_DRAFT_BACK,
    CB_DRAFT_OPEN_PREFIX,
    CB_DRAFT_DELETE_PREFIX,
    CB_DRAFT_REPLACE_PREFIX,
    CB_DRAFT_PREVIEW,
    CB_DRAFT_SAVE,
    CB_DRAFT_UNDO,
    CB_EDIT_PREFIX,
    CB_LIST_PREFIX,
    CB_RETRY_PREFIX,
    CB_SETTINGS_PREFIX,
    CB_SLUGSYNC,
    CB_SUBMIT_POST,
    CB_SUBMIT_UPDATE,
    CB_TMPL_PREFIX,
    CB_TOGGLEPUB_PREFIX,
    CB_UNDO_DELETE_PREFIX,
    CONFIRM_DELETE,
    CONFIRM_POST,
    CONFIRM_UPDATE,
    ENTER_API_KEY,
    ENTER_BODY,
    ENTER_DELETE_SLUG,
    ENTER_PUBLISH_CHOICE,
    ENTER_PUBLISH_CHOICE_UPDATE,
    ENTER_TITLE,
    ENTER_UPDATE_SLUG,
    ENTER_UPDATED_BODY,
    ENTER_UPDATED_TITLE,
)
from storage import enforce_config_permissions, load_users_data

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING
)


def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required.")

    # Enforce secure permissions before any file I/O
    enforce_config_permissions()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_users_data())

    builder = Application.builder().token(token)
    if hasattr(builder, "post_shutdown"):
        try:
            builder = builder.post_shutdown(h.close_http_client)
        except Exception:
            pass
    application = builder.build()

    conv_start = ConversationHandler(
        entry_points=[CommandHandler("start", h.start)],
        states={
            ENTER_API_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_api_key)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", h.cancel),
            CallbackQueryHandler(h.cancel, pattern=f"^{CB_CANCEL}$"),
        ],
    )

    conv_post = ConversationHandler(
        entry_points=[CommandHandler("post", h.post), CommandHandler("new", h.new_command)],
        states={
            ENTER_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_title)
            ],
            ENTER_BODY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_body),
                CommandHandler("done", h.draft_done),
                CommandHandler("preview", h.draft_preview),
                CommandHandler("clear", h.draft_clear),
                CallbackQueryHandler(h.draft_done_cb, pattern=f"^{CB_DRAFT_DONE}$"),
                CallbackQueryHandler(h.draft_preview_cb, pattern=f"^{CB_DRAFT_PREVIEW}$"),
                CallbackQueryHandler(h.draft_clear_cb, pattern=f"^{CB_DRAFT_CLEAR}$"),
                CallbackQueryHandler(h.draft_save_cb, pattern=f"^{CB_DRAFT_SAVE}$"),
                CallbackQueryHandler(h.draft_undo_cb, pattern=f"^{CB_DRAFT_UNDO}$"),
                CallbackQueryHandler(h.template_insert_cb, pattern=f"^{CB_TMPL_PREFIX}"),
                CallbackQueryHandler(h.cancel, pattern=f"^{CB_CANCEL}$"),
            ],
            ENTER_PUBLISH_CHOICE: [
                CallbackQueryHandler(
                    h.post_publish_choice, pattern=f"^({CB_CHOICE_DRAFT}|{CB_CHOICE_PUBLISH})$"
                )
            ],
            CONFIRM_POST: [
                CallbackQueryHandler(
                    h.confirm_post_handler, pattern=f"^{CB_SUBMIT_POST}$"
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", h.cancel),
            CallbackQueryHandler(h.cancel, pattern=f"^{CB_CANCEL}$"),
        ],
    )

    conv_update = ConversationHandler(
        entry_points=[
            CommandHandler("update", h.update_command),
            CallbackQueryHandler(h.inline_edit_start, pattern=f"^{CB_EDIT_PREFIX}"),
        ],
        states={
            ENTER_UPDATE_SLUG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_update_slug)
            ],
            ENTER_UPDATED_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_updated_title)
            ],
            ENTER_UPDATED_BODY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_updated_body)
            ],
            ENTER_PUBLISH_CHOICE_UPDATE: [
                CallbackQueryHandler(
                    h.update_publish_choice, pattern=f"^({CB_CHOICE_DRAFT}|{CB_CHOICE_PUBLISH})$"
                )
            ],
            CONFIRM_UPDATE: [
                CallbackQueryHandler(h.toggle_slug_sync, pattern=f"^{CB_SLUGSYNC}$"),
                CallbackQueryHandler(
                    h.confirm_update_handler, pattern=f"^{CB_SUBMIT_UPDATE}$"
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", h.cancel),
            CallbackQueryHandler(h.cancel, pattern=f"^{CB_CANCEL}$"),
        ],
    )

    conv_delete = ConversationHandler(
        entry_points=[
            CommandHandler("delete", h.delete_command),
            CallbackQueryHandler(h.inline_delete_start, pattern=f"^{CB_DELETE_PREFIX}"),
        ],
        states={
            ENTER_DELETE_SLUG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.enter_delete_slug)
            ],
            CONFIRM_DELETE: [
                CallbackQueryHandler(
                    h.confirm_delete_handler, pattern=f"^{CB_CONFIRM_DELETE}"
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", h.cancel),
            CallbackQueryHandler(h.cancel, pattern=f"^{CB_CANCEL}$"),
        ],
    )

    application.add_handler(conv_start)
    application.add_handler(conv_post)
    application.add_handler(conv_update)
    application.add_handler(conv_delete)

    application.add_handler(CommandHandler("list", h.list_command))
    application.add_handler(CommandHandler("search", h.search_command))
    application.add_handler(CommandHandler("help", h.help_command))
    application.add_handler(CommandHandler("cancel", h.cancel))
    application.add_handler(CommandHandler("save", h.save_draft_command))
    application.add_handler(CommandHandler("drafts", h.drafts_command))
    application.add_handler(CommandHandler("settings", h.settings_command))
    application.add_handler(CommandHandler("status", h.status_command))

    # Callback handlers outside conversations
    application.add_handler(CallbackQueryHandler(h.list_callback, pattern=f"^{CB_LIST_PREFIX}"))
    application.add_handler(
        CallbackQueryHandler(
            h.drafts_callback,
            pattern=f"^({CB_DRAFT_OPEN_PREFIX}|{CB_DRAFT_DELETE_PREFIX}|{CB_DRAFT_REPLACE_PREFIX}|{CB_DRAFT_BACK})",
        )
    )
    application.add_handler(CallbackQueryHandler(h.toggle_publish_handler, pattern=f"^{CB_TOGGLEPUB_PREFIX}"))
    application.add_handler(CallbackQueryHandler(h.settings_callback, pattern=f"^{CB_SETTINGS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(h.undo_delete_handler, pattern=f"^{CB_UNDO_DELETE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(h.retry_handler, pattern=f"^{CB_RETRY_PREFIX}"))

    application.add_error_handler(h.error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
