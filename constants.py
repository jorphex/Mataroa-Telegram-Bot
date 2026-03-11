import re
from enum import IntEnum
from typing import Dict

# ---------- Constants ----------
DEFAULT_PREVIEW_LENGTH = 280
POSTS_PAGE_SIZE = 5
POSTS_CACHE_TTL = 10.0
HTTP_TIMEOUT = 12.0
MAX_PREVIEW_CHARS = 3900  # safe cap below Telegram 4096 limit
MAX_BUTTON_TEXT = 64

DRAFT_COOLDOWN_SEC = 1.5
LIST_COOLDOWN_SEC = 1.0
SAVE_DEBOUNCE_SEC = 1.5
API_MAX_RETRIES = 2
API_RETRY_BACKOFF = 0.6
DELETE_GRACE_SEC = 15
DRAFTS_MAX = 20

ALLOWED_PREVIEW_LENGTHS = {140, 280, 500}
ALLOWED_PREVIEW_FORMATS = {"markdown", "plain"}
SLUG_RE = re.compile(r"^[a-z0-9-]{1,128}$")

TEMPLATES = {
    "outline": "# Outline\n- Intro\n- Body\n- Conclusion\n",
    "notes": "# Notes\n- Point 1\n- Point 2\n",
    "links": "# Links\n- [Title](https://example.com) - note\n",
}

# ---------- Messages ----------
MESSAGES: Dict[str, str] = {
    # Generic/system
    "PLEASE_WAIT": "⏳ Please wait...",
    "ACCESS_DENIED": "Access denied.",
    "NEED_API_KEY": "🔑 Set your API key first using /start.",
    "INVALID_ACTION": "Invalid action.",
    "INVALID_OR_STALE_ACTION": "Invalid or stale action.",
    "OP_CANCELLED": "Operation cancelled.",
    "PRIVACY_DM": "For privacy, please use me in a private chat.",
    "SET_API_PRIVATE": "For security, please message me in a private chat to set your API key.",

    # Start/Help/Status
    "START_WELCOME": "👋 Welcome to the Mataroa.blog bot! Please enter your API key.",
    "API_SAVED": "✅ API key saved! Use /new, /update, /delete, /list, /search, /settings or /help. Tip: use /list published or /list drafts to filter.",
    "HELP_TEXT": (
        "🤖 Mataroa.blog Bot Help\n\n"
        "/start - Set your API key\n"
        "/new or /post - Create a new post (multi-message drafting: /done, /preview, /clear, /cancel)\n"
        "/save - Save your current draft\n"
        "/drafts - List saved drafts\n"
        "/update - Update an existing post\n"
        "/delete - Delete a post\n"
        "/list - List your posts with filters & pagination (use /list published or /list drafts)\n"
        "/search <query> - Search in titles and bodies\n"
        "/settings - Adjust default publish mode, preview length, confirm-delete\n"
        "/status - Check API connectivity\n"
    ),
    "STATUS_API_REACHABLE": "✅ API reachable. {ms} ms",
    "STATUS_API_UNREACHABLE": "❌ API unreachable or unauthorized.",

    # Draft/new post flow
    "RESUME_DRAFT": "📝 Resuming draft: {title}\nSend message chunks to append. Use /done when finished.",
    "ENTER_TITLE_PROMPT": "📝 Enter the title of your post:",
    "NOW_SEND_BODY": "✏️ Now send the body in multiple messages. Use /done when finished.",
    "SEND_BODY_MULTIMSG": "✏️ Send the body/content in multiple messages. Use /done when finished.\nCommands: /preview /clear /cancel",
    "PROMPT_VALID_TITLE": "Please provide a valid title:",
    "PROMPT_VALID_CONTENT": "Please provide valid content:",
    "ADDED_TO_DRAFT": "✅ Added to draft. Use /preview or /done.",
    "DRAFT_CLEARED": "🧹 Draft cleared.",
    "DRAFT_SAVED": "✅ Draft saved.",
    "DRAFT_SAVED_AS": "✅ Draft saved: {title}",
    "DRAFTS_HEADER": "📚 Saved drafts ({count}):",
    "DRAFTS_EMPTY": "No saved drafts yet.",
    "DRAFT_LOADED": "✅ Draft loaded: {title}\nUse /post to continue.",
    "DRAFT_DELETED": "🗑️ Draft deleted: {title}",
    "DRAFT_REPLACE_CONFIRM": "Replace your current draft with '{title}'?",
    "REMOVED_LAST_CHUNK": "↩️ Removed last chunk.",
    "NOTHING_TO_UNDO": "Nothing to undo.",
    "DRAFT_EMPTY": "Draft is empty. Add content first.",
    "CHOOSE_PUBLICATION_OPTION": "Choose publication option:",

    # Update flow
    "ENTER_UPDATE_SLUG_PROMPT": "✏️ Enter the slug of the post to update:",
    "FAILED_FETCH_POST_DETAILS": "❌ Failed to fetch post details.",
    "FAILED_FETCH_POST_DETAILS_CHECK": "❌ Failed to fetch post details. Check the slug and try again.",
    "CURRENT_TITLE_LABEL": "Current Title:",
    "CURRENT_BODY_LABEL": "Current Body:",
    "ENTER_UPDATED_TITLE": "Enter the updated title:",
    "ENTER_UPDATED_BODY": "Enter the updated body/content:",
    "SLUG_SUGGESTION_NOTE_MD": "\n\nSlug suggestion: {current} → {suggested} \\(toggle before submit\\)",
    "SLUG_SUGGESTION_UNAVAILABLE": "Slug suggestion unavailable. Adjust title.",

    # Create/update results
    "POST_CREATED": "✅ Post created.",
    "POST_CREATED_WITH_DETAILS": "✅ Post created!\nSlug: {slug}\nStatus: {status}\nURL: {url}",
    "FAILED_CREATE_POST": "❌ Failed to create post.",
    "POST_UPDATED_WITH_DETAILS": "✅ Post updated!\nSlug: {slug}\nURL: {url}",
    "FAILED_UPDATE_POST": "❌ Failed to update post.",

    # Delete flow
    "PROMPT_VALID_SLUG": "Please enter a valid slug:",
    "INVALID_SLUG": "❌ Invalid slug.",
    "CONFIRM_DELETE": "⚠️ Are you sure you want to delete post '{slug}'?",
    "DELETING_IN": "🗑️ Deleting '{slug}' in {seconds}s...",
    "POST_DELETED": "✅ Post with slug '{slug}' deleted.",
    "FAILED_DELETE_POST_FMT": "❌ Failed to delete '{slug}'.",
    "FAILED_DELETE_POST_SIMPLE": "❌ Failed to delete post.",
    "UNDO_DELETE_CANCELLED": "❎ Deletion of '{slug}' cancelled.",
    "TOO_LATE_UNDO": "Too late to undo, or no pending deletion.",

    # List/search
    "FAILED_FETCH_POSTS": "❌ Failed to fetch posts. Try again later.",
    "LIST_HEADER": "📄 Your Posts ({total}):",
    "LIST_NO_MATCH": "(No posts match your criteria.)",
    "USAGE_SEARCH": "Usage: /search <query>",

    # Toggle publish
    "FAILED_FETCH_FOR_TOGGLE": "❌ Failed to fetch post for toggling.",
    "TOGGLED_PUBLISH_STATE": "✅ Toggled publish state.",
    "FAILED_TOGGLE_PUBLISH": "❌ Failed to toggle publish.",

    # Retry
    "NO_ACTION_TO_RETRY": "No action to retry.",
    "UNSUPPORTED_RETRY": "Unsupported retry.",

    # Buttons/labels
    "BUTTON_CANCEL": "Cancel",
    "BUTTON_DONE": "Done",
    "BUTTON_PREVIEW": "Preview",
    "BUTTON_CLEAR": "Clear",
    "BUTTON_UNDO_LAST": "Undo last",
    "BUTTON_DRAFT_SAVE": "Save Draft",
    "BUTTON_DRAFT_OPEN": "Open",
    "BUTTON_DRAFT_DELETE": "Delete",
    "BUTTON_DRAFT_REPLACE": "Replace",
    "BUTTON_TEMPLATE_OUTLINE": "Template: Outline",
    "BUTTON_TEMPLATE_NOTES": "Template: Notes",
    "BUTTON_TEMPLATE_LINKS": "Template: Links",
    "BUTTON_SAVE_DRAFT": "Save as Draft",
    "BUTTON_PUBLISH_NOW": "Publish Now",
    "BUTTON_SUBMIT": "Submit",
    "BUTTON_TOGGLE_SLUGSYNC": "Toggle Slug Sync",
    "BUTTON_EDIT": "Edit",
    "BUTTON_DELETE": "Delete",
    "BUTTON_UNDO_DELETE": "Undo delete",
    "BUTTON_OPEN": "Open",
    "BUTTON_SHARE": "Share",
    "BUTTON_PREV": "◀️ Prev",
    "BUTTON_NEXT": "Next ▶️",
    "BUTTON_REFRESH": "Refresh",
    "BUTTON_YES_DELETE": "Yes, Delete",
    "BUTTON_RETRY": "Retry",
    "FILTER_ALL": "All",
    "FILTER_PUBLISHED": "Published",
    "FILTER_DRAFTS": "Drafts",
    "BUTTON_BACK_TO_LIST": "Back to list",
    "BUTTON_PUBLISH": "Publish",
    "BUTTON_UNPUBLISH": "Unpublish",
    # Settings additions
    "SETTINGS_HEADER": "⚙️ Settings",
    "BUTTON_TOGGLE_DEFAULT_MODE": "Toggle Default Publish Mode",
    "BUTTON_TOGGLE_PREVIEW_FORMAT": "Toggle Preview Format",
    "BUTTON_TOGGLE_CONFIRM_DELETE": "Toggle Confirm Before Delete",
}

# ---------- Callback Data Tokens ----------
CB_CANCEL = "cancel"
CB_DRAFT_DONE = "draft:done"
CB_DRAFT_PREVIEW = "draft:preview"
CB_DRAFT_CLEAR = "draft:clear"
CB_DRAFT_UNDO = "draft:undo"
CB_DRAFT_SAVE = "draft:save"
CB_DRAFT_OPEN_PREFIX = "draft:open:"
CB_DRAFT_DELETE_PREFIX = "draft:del:"
CB_DRAFT_REPLACE_PREFIX = "draft:replace:"
CB_DRAFT_BACK = "draft:back"
CB_TMPL_PREFIX = "tmpl:"
CB_CHOICE_DRAFT = "draft"
CB_CHOICE_PUBLISH = "publish"
CB_SUBMIT_POST = "submit_post"
CB_SUBMIT_UPDATE = "submit_update"
CB_SLUGSYNC = "slugsync"
CB_EDIT_PREFIX = "edit:"
CB_DELETE_PREFIX = "delete:"
CB_TOGGLEPUB_PREFIX = "togglepub:"
CB_LIST_PREFIX = "list:"
CB_LIST_FILTER_PREFIX = "list:filter:"
CB_LIST_PAGE_PREFIX = "list:page:"
CB_LIST_REFRESH = "list:refresh"
CB_CONFIRM_DELETE = "confirm_delete"
CB_UNDO_DELETE_PREFIX = "undodel:"
CB_RETRY_PREFIX = "retry:"
CB_RETRY_CREATE = "retry:create"
CB_RETRY_UPDATE = "retry:update"
CB_RETRY_DELETE = "retry:delete"
CB_RETRY_TOGGLEPUB = "retry:togglepub"
CB_SETTINGS_PREFIX = "settings:"
CB_SETTINGS_MODE = "settings:mode"
CB_SETTINGS_PREV_PREFIX = "settings:prev:"
CB_SETTINGS_FORMAT = "settings:format"
CB_SETTINGS_CONFIRM = "settings:confirm"

# ---------- Context Keys ----------
K_TITLE = "title"
K_BODY = "body"
K_BODY_PARTS = "body_parts"
K_UNDO_STACK = "undo_stack"
K_LIST_STATE = "list_state"
K_SLUG_SYNC = "slug_sync"
K_FINAL_SLUG = "final_slug"
K_PUBLISHED_AT = "published_at"
K_CURRENT_SLUG = "current_slug"
K_SLUG = "slug"
K_CURRENT_TITLE = "current_title"
K_CURRENT_BODY = "current_body"
K_SLUG_SUGGESTED = "slug_suggested"
K_SLUG_SUGGESTED_VALID = "slug_suggested_valid"
K_POSTS_CACHE = "posts_cache"
K_SAVE_JOB = "save_job"


# ---------- Conversation States ----------
class ConvState(IntEnum):
    ENTER_API_KEY = 0
    ENTER_TITLE = 1
    ENTER_BODY = 2
    ENTER_PUBLISH_CHOICE = 3
    ENTER_DELETE_SLUG = 4
    ENTER_UPDATE_SLUG = 5
    ENTER_UPDATED_TITLE = 6
    ENTER_UPDATED_BODY = 7
    ENTER_PUBLISH_CHOICE_UPDATE = 8
    CONFIRM_POST = 9
    CONFIRM_UPDATE = 10
    CONFIRM_DELETE = 11


# Keep original state names for minimal code changes
ENTER_API_KEY = ConvState.ENTER_API_KEY
ENTER_TITLE = ConvState.ENTER_TITLE
ENTER_BODY = ConvState.ENTER_BODY
ENTER_PUBLISH_CHOICE = ConvState.ENTER_PUBLISH_CHOICE
ENTER_DELETE_SLUG = ConvState.ENTER_DELETE_SLUG
ENTER_UPDATE_SLUG = ConvState.ENTER_UPDATE_SLUG
ENTER_UPDATED_TITLE = ConvState.ENTER_UPDATED_TITLE
ENTER_UPDATED_BODY = ConvState.ENTER_UPDATED_BODY
ENTER_PUBLISH_CHOICE_UPDATE = ConvState.ENTER_PUBLISH_CHOICE_UPDATE
CONFIRM_POST = ConvState.CONFIRM_POST
CONFIRM_UPDATE = ConvState.CONFIRM_UPDATE
CONFIRM_DELETE = ConvState.CONFIRM_DELETE


# API and bot settings
API_URL = "https://mataroa.blog/api/posts/"
