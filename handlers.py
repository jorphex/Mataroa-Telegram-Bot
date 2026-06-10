# ruff: noqa: F401
"""Compatibility facade for bot handlers.

Feature code lives in smaller handler_* modules; mataroa.py imports this module
to keep the Telegram router stable.
"""

from handler_basic import cancel, enter_api_key, help_command, start
from handler_delete import (
    confirm_delete_handler,
    confirm_delete_prompt,
    delete_command,
    delete_retry_keyboard,
    enter_delete_slug,
    execute_delete_job,
    get_pending_deletes_map,
    inline_delete_start,
    notify_delete_result,
    schedule_delete_with_undo,
    schedule_delete_with_undo_message,
    undo_delete_handler,
)
from handler_drafts import (
    draft_clear,
    draft_clear_cb,
    draft_done,
    draft_done_cb,
    draft_preview,
    draft_preview_cb,
    draft_save_cb,
    draft_undo_cb,
    drafts_callback,
    drafts_command,
    enter_body,
    enter_title,
    new_command,
    post,
    save_draft_command,
    template_insert_cb,
)
from handler_lists import (
    fetch_posts_for_user,
    list_callback,
    list_command,
    list_posts,
    search_command,
    toggle_publish_handler,
)
from handler_posts import (
    _submit_create_post,
    _submit_update_post,
    confirm_post_handler,
    confirm_update_handler,
    enter_update_slug,
    enter_updated_body,
    enter_updated_title,
    inline_edit_start,
    post_publish_choice,
    toggle_slug_sync,
    update_command,
    update_publish_choice,
)
from handler_settings import (
    build_settings_keyboard,
    build_settings_text,
    error_handler,
    retry_handler,
    settings_callback,
    settings_command,
    status_command,
)
from handler_ui import (
    build_manage_post_view,
    cancel_keyboard,
    drafting_keyboard,
    publish_choice_keyboard,
)
from handler_utils import (
    allowed_user_ids,
    api_call,
    close_http_client,
    ensure_allowed,
    extract_message_text,
    save_users_data,
    schedule_users_data_save,
)
