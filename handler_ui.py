# ruff: noqa: F403, F405

from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from constants import *
from handler_state import _drafts_map, token_for_slug
from handler_utils import (
    clamp_button_text,
    is_valid_absolute_url,
    mdv2,
    safe_truncate_md,
    safe_truncate_text,
    truncate,
)

def cancel_keyboard() -> InlineKeyboardMarkup:
    """Build a Cancel inline keyboard."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL)]])


def drafting_keyboard() -> InlineKeyboardMarkup:
    """Build the drafting controls keyboard (done/preview/clear/undo/templates)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(MESSAGES["BUTTON_DONE"], callback_data=CB_DRAFT_DONE),
                InlineKeyboardButton(MESSAGES["BUTTON_PREVIEW"], callback_data=CB_DRAFT_PREVIEW),
                InlineKeyboardButton(MESSAGES["BUTTON_DRAFT_SAVE"], callback_data=CB_DRAFT_SAVE),
            ],
            [
                InlineKeyboardButton(MESSAGES["BUTTON_CLEAR"], callback_data=CB_DRAFT_CLEAR),
                InlineKeyboardButton(MESSAGES["BUTTON_UNDO_LAST"], callback_data=CB_DRAFT_UNDO),
            ],
            [
                InlineKeyboardButton(MESSAGES["BUTTON_TEMPLATE_OUTLINE"], callback_data=f"{CB_TMPL_PREFIX}outline"),
                InlineKeyboardButton(MESSAGES["BUTTON_TEMPLATE_NOTES"], callback_data=f"{CB_TMPL_PREFIX}notes"),
            ],
            [
                InlineKeyboardButton(MESSAGES["BUTTON_TEMPLATE_LINKS"], callback_data=f"{CB_TMPL_PREFIX}links"),
                InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL),
            ],
        ]
    )


def publish_choice_keyboard(default_mode: Optional[str] = None) -> InlineKeyboardMarkup:
    """Build keyboard to choose draft vs publish (with default marked)."""
    draft_label = MESSAGES["BUTTON_SAVE_DRAFT"]
    publish_label = MESSAGES["BUTTON_PUBLISH_NOW"]
    if default_mode == "draft":
        draft_label += " ✓"
    elif default_mode == "publish":
        publish_label += " ✓"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(draft_label, callback_data=CB_CHOICE_DRAFT),
                InlineKeyboardButton(publish_label, callback_data=CB_CHOICE_PUBLISH),
            ],
            [InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL)],
        ]
    )


def preview_submit_keyboard(include_slug_sync: bool = False) -> InlineKeyboardMarkup:
    """Build keyboard to submit a new post (optionally include slug sync toggle)."""
    row = [InlineKeyboardButton(MESSAGES["BUTTON_SUBMIT"], callback_data=CB_SUBMIT_POST)]
    if include_slug_sync:
        row.append(InlineKeyboardButton(MESSAGES["BUTTON_TOGGLE_SLUGSYNC"], callback_data=CB_SLUGSYNC))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL)]])


def update_preview_submit_keyboard(include_slug_sync: bool = True) -> InlineKeyboardMarkup:
    """Build keyboard to submit an updated post (optionally include slug sync toggle)."""
    row1 = [InlineKeyboardButton(MESSAGES["BUTTON_SUBMIT"], callback_data=CB_SUBMIT_UPDATE)]
    if include_slug_sync:
        row1.append(InlineKeyboardButton(MESSAGES["BUTTON_TOGGLE_SLUGSYNC"], callback_data=CB_SLUGSYNC))
    return InlineKeyboardMarkup([row1, [InlineKeyboardButton(MESSAGES["BUTTON_CANCEL"], callback_data=CB_CANCEL)]])
def render_create_preview(title: str, body: str, published_at: Optional[str]) -> str:
    """Render MarkdownV2 preview for new post creation under MAX_PREVIEW_CHARS cap."""
    status = "Draft" if published_at is None else "Published"
    title_s = mdv2(title)
    body_s = mdv2(body)
    header_pre = "*Preview Post:*\n\n" + "*Title:*\n"
    header_post = "\n\n*Body:*\n"
    footer = "\n\n*Status:*\n" + mdv2(status)

    # First try to fit body; if overflow, shrink title; ensure total under MAX_PREVIEW_CHARS
    body_allowed = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + body_s + footer)
    if body_allowed < 0:
        # Try shrinking title first (set body to zero for budget calc)
        title_allowed = MAX_PREVIEW_CHARS - len(header_pre + header_post + footer)
        title_allowed = max(0, title_allowed)
        if len(title_s) > title_allowed:
            title_s = safe_truncate_md(title_s, title_allowed)
        # Recompute body allowance after title truncation
        body_allowed = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + footer)
        body_allowed = max(0, body_allowed)
        body_s = safe_truncate_md(body_s, body_allowed)
    else:
        # Ensure body within allowed maximum
        max_body = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + footer)
        if max_body < len(body_s):
            body_s = safe_truncate_md(body_s, max(0, max_body))

    return header_pre + title_s + header_post + body_s + footer


def render_create_preview_plain(title: str, body: str, published_at: Optional[str]) -> str:
    """Render plain-text preview for new post creation under MAX_PREVIEW_CHARS cap."""
    status = "Draft" if published_at is None else "Published"
    title_s = title or ""
    body_s = body or ""
    header_pre = "Preview Post:\n\nTitle:\n"
    header_post = "\n\nBody:\n"
    footer = "\n\nStatus:\n" + status

    body_allowed = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + body_s + footer)
    if body_allowed < 0:
        title_allowed = MAX_PREVIEW_CHARS - len(header_pre + header_post + footer)
        title_allowed = max(0, title_allowed)
        if len(title_s) > title_allowed:
            title_s = safe_truncate_text(title_s, title_allowed)
        body_allowed = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + footer)
        body_allowed = max(0, body_allowed)
        body_s = safe_truncate_text(body_s, body_allowed)
    else:
        max_body = MAX_PREVIEW_CHARS - len(header_pre + title_s + header_post + footer)
        if max_body < len(body_s):
            body_s = safe_truncate_text(body_s, max(0, max_body))

    return header_pre + title_s + header_post + body_s + footer


def render_update_preview(
    title: str,
    body: str,
    published_at: Optional[str],
    current_slug: str,
    suggested: str,
    slug_sync: bool,
) -> str:
    """Render MarkdownV2 preview for post update, including slug change indication."""
    status = "Draft" if published_at is None else "Published"
    title_s = mdv2(title)
    body_s = mdv2(body)
    slug_line = mdv2(current_slug)
    if current_slug != suggested:
        slug_line = f"{mdv2(current_slug)} → {mdv2(suggested)}"
    sync_state = "sync ON" if slug_sync else "sync OFF"

    header_pre = "*Preview Updated Post:*\n\n" + "*Title:*\n"
    header_post = "\n\n*Body:*\n"
    tail_pre = "\n\n*Slug:*\n"
    tail_mid = f" \\({mdv2(sync_state)}\\)"
    tail_post = "\n\n*Status:*\n" + mdv2(status)

    # Attempt to fit content under MAX_PREVIEW_CHARS; shrink body first, then title, then slug line
    total_len = len(
        header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
    )
    if total_len > MAX_PREVIEW_CHARS:
        # 1) Shrink body
        body_allowed = MAX_PREVIEW_CHARS - len(
            header_pre + title_s + header_post + tail_pre + slug_line + tail_mid + tail_post
        )
        if body_allowed < 0:
            body_s = ""
        else:
            body_s = safe_truncate_md(body_s, body_allowed)
        # 2) Re-evaluate; shrink title if needed
        total_len = len(
            header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
        )
        if total_len > MAX_PREVIEW_CHARS:
            title_allowed = MAX_PREVIEW_CHARS - len(
                header_pre + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
            )
            title_allowed = max(0, title_allowed)
            if len(title_s) > title_allowed:
                title_s = safe_truncate_md(title_s, title_allowed)
        # 3) Re-evaluate; shrink slug line if still needed
        total_len = len(
            header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
        )
        if total_len > MAX_PREVIEW_CHARS:
            slug_allowed = MAX_PREVIEW_CHARS - len(
                header_pre + title_s + header_post + body_s + tail_pre + tail_mid + tail_post
            )
            slug_allowed = max(0, slug_allowed)
            if len(slug_line) > slug_allowed:
                slug_line = safe_truncate_md(slug_line, slug_allowed)

    return header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post


def render_update_preview_plain(
    title: str,
    body: str,
    published_at: Optional[str],
    current_slug: str,
    suggested: str,
    slug_sync: bool,
) -> str:
    """Render plain-text preview for post update, including slug change indication."""
    status = "Draft" if published_at is None else "Published"
    title_s = title or ""
    body_s = body or ""
    slug_line = current_slug or ""
    if current_slug != suggested:
        slug_line = f"{current_slug} -> {suggested}"
    sync_state = "sync ON" if slug_sync else "sync OFF"

    header_pre = "Preview Updated Post:\n\nTitle:\n"
    header_post = "\n\nBody:\n"
    tail_pre = "\n\nSlug:\n"
    tail_mid = f" ({sync_state})"
    tail_post = "\n\nStatus:\n" + status

    total_len = len(
        header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
    )
    if total_len > MAX_PREVIEW_CHARS:
        body_allowed = MAX_PREVIEW_CHARS - len(
            header_pre + title_s + header_post + tail_pre + slug_line + tail_mid + tail_post
        )
        if body_allowed < 0:
            body_s = ""
        else:
            body_s = safe_truncate_text(body_s, body_allowed)
        total_len = len(
            header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
        )
        if total_len > MAX_PREVIEW_CHARS:
            title_allowed = MAX_PREVIEW_CHARS - len(
                header_pre + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
            )
            title_allowed = max(0, title_allowed)
            if len(title_s) > title_allowed:
                title_s = safe_truncate_text(title_s, title_allowed)
        total_len = len(
            header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
        )
        if total_len > MAX_PREVIEW_CHARS:
            slug_allowed = MAX_PREVIEW_CHARS - len(
                header_pre + title_s + header_post + body_s + tail_pre + tail_mid + tail_post
            )
            slug_allowed = max(0, slug_allowed)
            if len(slug_line) > slug_allowed:
                slug_line = safe_truncate_text(slug_line, slug_allowed)

    return header_pre + title_s + header_post + body_s + tail_pre + slug_line + tail_mid + tail_post
def open_url_button(url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(MESSAGES["BUTTON_OPEN"], url=url)


def share_url_button(url: str) -> InlineKeyboardButton:
    # Telegram doesn't support copy-to-clipboard; using URL open for share
    return InlineKeyboardButton(MESSAGES["BUTTON_SHARE"], url=url)
def list_nav_keyboard(
    filter_mode: str, page: int, total_pages: int
) -> List[List[InlineKeyboardButton]]:
    """Build navigation and filter controls for the posts list view."""
    btns = []
    # Filters
    btns.append(
        [
            InlineKeyboardButton(
                f"{MESSAGES['FILTER_ALL']}{' ✓' if filter_mode=='all' else ''}", callback_data=f"{CB_LIST_FILTER_PREFIX}all"
            ),
            InlineKeyboardButton(
                f"{MESSAGES['FILTER_PUBLISHED']}{' ✓' if filter_mode=='published' else ''}",
                callback_data=f"{CB_LIST_FILTER_PREFIX}published",
            ),
            InlineKeyboardButton(
                f"{MESSAGES['FILTER_DRAFTS']}{' ✓' if filter_mode=='drafts' else ''}", callback_data=f"{CB_LIST_FILTER_PREFIX}drafts"
            ),
        ]
    )
    # Paging
    nav = []
    if page > 1:
        prev_label = f"{MESSAGES['BUTTON_PREV']} ({page}/{total_pages})"
        nav.append(InlineKeyboardButton(prev_label, callback_data=f"{CB_LIST_PAGE_PREFIX}prev"))
    if page < total_pages:
        next_label = f"{MESSAGES['BUTTON_NEXT']} ({page}/{total_pages})"
        nav.append(InlineKeyboardButton(next_label, callback_data=f"{CB_LIST_PAGE_PREFIX}next"))
    if nav:
        btns.append(nav)
    # Refresh
    btns.append([InlineKeyboardButton(MESSAGES["BUTTON_REFRESH"], callback_data=CB_LIST_REFRESH)])
    return btns


def build_post_row_buttons(post: dict, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> List[List[InlineKeyboardButton]]:
    """Build per-post single 'Manage • <title>' button for list view using tokenized callback data."""
    slug = post.get("slug", "")
    title = post.get("title", "No Title")
    label = clamp_button_text(f"Manage • {title}")
    token = token_for_slug(context, user_id, slug) if slug else ""
    return [[InlineKeyboardButton(label, callback_data=f"{CB_LIST_PREFIX}manage:{token}")]]


def build_list_message(
    posts: List[dict],
    filter_mode: str,
    page: int,
    query: Optional[str],
    preview_length: int,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    user_id: Optional[int] = None,
) -> Tuple[str, InlineKeyboardMarkup, int]:
    """Build list text (MarkdownV2) and keyboard; returns (message, keyboard, page_used)."""
    # Filter
    filtered = posts
    if filter_mode == "published":
        filtered = [p for p in posts if p.get("published_at")]
    elif filter_mode == "drafts":
        filtered = [p for p in posts if not p.get("published_at")]
    if query:
        q = query.lower()
        filtered = [
            p
            for p in filtered
            if q in (p.get("title", "").lower() + " " + p.get("body", "").lower())
        ]

    total = len(filtered)
    total_pages = max(1, (total + POSTS_PAGE_SIZE - 1) // POSTS_PAGE_SIZE)
    page_clamped = max(1, min(page, total_pages))
    start = (page_clamped - 1) * POSTS_PAGE_SIZE
    page_posts = filtered[start : start + POSTS_PAGE_SIZE]

    header = mdv2(MESSAGES["LIST_HEADER"].format(total=total))
    lines: List[str] = [header, mdv2(f"Page {page_clamped}/{total_pages}")]
    for p in page_posts:
        title = p.get("title", "No Title")
        slug = p.get("slug", "")
        is_pub = bool(p.get("published_at"))
        status = "🟢" if is_pub else "📝"
        preview_raw = truncate(p.get("body", ""), preview_length)
        title_md = mdv2(title)
        slug_md = mdv2(slug)
        preview_md = mdv2(preview_raw)
        lines.append(f"\n{status} *{title_md}*\n{slug_md}\n{preview_md}")
    if not page_posts:
        lines.append(f"\n{mdv2(MESSAGES['LIST_NO_MATCH'])}")

    # Build keyboard with per post manage buttons and nav
    rows: List[List[InlineKeyboardButton]] = []
    for p in page_posts:
        if context is not None and user_id is not None:
            rows += build_post_row_buttons(p, context, user_id)
        else:
            # Fallback (should not happen): disable manage if no context/user
            pass
    rows += list_nav_keyboard(filter_mode, page_clamped, total_pages)

    return "\n".join(lines), InlineKeyboardMarkup(rows), page_clamped


def build_manage_post_view(
    post: dict,
    slug: str,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Build the manage-post message and controls for a single post."""
    title = post.get("title", "No Title")
    url = post.get("url", "")
    is_pub = bool(post.get("published_at"))
    status = "Published" if is_pub else "Draft"
    text = (
        f"*🛠 Manage Post*\n\n"
        f"*Title:*\n{mdv2(title)}\n\n"
        f"*Slug:*\n{mdv2(slug)}\n\n"
        f"*Status:*\n{mdv2(status)}"
    )
    token = token_for_slug(context, user_id, slug)
    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(MESSAGES["BUTTON_EDIT"], callback_data=f"{CB_EDIT_PREFIX}{token}"),
            InlineKeyboardButton(MESSAGES["BUTTON_DELETE"], callback_data=f"{CB_DELETE_PREFIX}{token}"),
        ]
    ]
    toggle_label = MESSAGES["BUTTON_UNPUBLISH"] if is_pub else MESSAGES["BUTTON_PUBLISH"]
    actions = [
        InlineKeyboardButton(toggle_label, callback_data=f"{CB_TOGGLEPUB_PREFIX}{token}")
    ]
    if is_valid_absolute_url(url):
        actions.append(open_url_button(url))
    rows.append(actions)
    rows.append(
        [
            InlineKeyboardButton(
                MESSAGES["BUTTON_BACK_TO_LIST"], callback_data=f"{CB_LIST_PREFIX}back"
            )
        ]
    )
    return text, InlineKeyboardMarkup(rows)
def build_drafts_message(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    drafts = _drafts_map(user_id)
    if not drafts:
        return MESSAGES["DRAFTS_EMPTY"], InlineKeyboardMarkup([])
    ordered = sorted(drafts.items(), key=lambda item: item[1].get("updated_ts", 0.0), reverse=True)
    lines = [MESSAGES["DRAFTS_HEADER"].format(count=len(ordered))]
    rows: List[List[InlineKeyboardButton]] = []
    for idx, (did, dval) in enumerate(ordered, start=1):
        title = dval.get("title", "Untitled draft")
        updated = dval.get("updated_at", "")
        lines.append(f"{idx}. {title} ({updated})" if updated else f"{idx}. {title}")
        open_label = clamp_button_text(f"{MESSAGES['BUTTON_DRAFT_OPEN']} • {title}")
        rows.append(
            [
                InlineKeyboardButton(open_label, callback_data=f"{CB_DRAFT_OPEN_PREFIX}{did}"),
                InlineKeyboardButton(
                    MESSAGES["BUTTON_DRAFT_DELETE"],
                    callback_data=f"{CB_DRAFT_DELETE_PREFIX}{did}",
                ),
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(rows)
