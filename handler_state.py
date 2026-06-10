# ruff: noqa: F403, F405

from datetime import datetime
import secrets
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from telegram.ext import ContextTypes

from constants import *
from handler_utils import cooldown_ok
from storage import UserData, users_data

def _get_user_bucket(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Dict[str, Any]:
    try:
        app_ud = context.application.user_data  # type: ignore[attr-defined]
    except Exception:
        app_ud = {}
    ud = app_ud.get(user_id)
    if ud is None:
        ud = {}
        app_ud[user_id] = ud
    return ud


def get_token_maps(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Tuple[Dict[str, str], Dict[str, str]]:
    ud = _get_user_bucket(context, user_id)
    t2s = ud.get("tokens")
    if t2s is None:
        t2s = {}
        ud["tokens"] = t2s
    s2t = ud.get("rev_tokens")
    if s2t is None:
        s2t = {}
        ud["rev_tokens"] = s2t
    return t2s, s2t


def _gen_token(existing: Set[str]) -> str:
    # 8-char base36 token
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    while True:
        n = secrets.randbits(40)
        s = ""
        while n:
            n, r = divmod(n, 36)
            s = alphabet[r] + s
        if not s:
            s = "0"
        token = s[:8] if len(s) >= 8 else s.rjust(8, "0")
        if token not in existing:
            return token


def token_for_slug(context: ContextTypes.DEFAULT_TYPE, user_id: int, slug: str) -> str:
    t2s, s2t = get_token_maps(context, user_id)
    if slug in s2t:
        return s2t[slug]
    token = _gen_token(set(t2s.keys()))
    t2s[token] = slug
    s2t[slug] = token
    return token


def resolve_token_to_slug(context: ContextTypes.DEFAULT_TYPE, user_id: int, token_or_slug: str) -> Optional[str]:
    t2s, s2t = get_token_maps(context, user_id)
    if token_or_slug in t2s:
        return t2s[token_or_slug]
    # Back-compat: if value itself looks like a slug, accept and register
    if is_valid_slug(token_or_slug):
        token_for_slug(context, user_id, token_or_slug)
        return token_or_slug
    return None
def get_list_state(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    state = context.user_data.get(K_LIST_STATE)
    if not isinstance(state, dict):
        state = {"filter": "all", "page": 1, "query": None}
        context.user_data[K_LIST_STATE] = state
    return state


def set_list_state(context: ContextTypes.DEFAULT_TYPE, state: Dict[str, Any]) -> None:
    context.user_data[K_LIST_STATE] = state


def get_draft_parts(context: ContextTypes.DEFAULT_TYPE) -> List[str]:
    parts = context.user_data.get(K_BODY_PARTS)
    if not isinstance(parts, list):
        parts = []
        context.user_data[K_BODY_PARTS] = parts
    return parts


def set_draft_parts(context: ContextTypes.DEFAULT_TYPE, parts: List[str]) -> None:
    context.user_data[K_BODY_PARTS] = list(parts)


def _clear_active_draft(
    user_id: int, context: ContextTypes.DEFAULT_TYPE, *, clear_title: bool = True
) -> None:
    """Clear active in-memory and persistent draft state for a user."""
    if clear_title:
        context.user_data.pop(K_TITLE, None)
    context.user_data.pop(K_BODY, None)
    context.user_data[K_BODY_PARTS] = []
    context.user_data[K_UNDO_STACK] = []
    u = users_data[user_id]
    if clear_title:
        u.draft_title = ""
    u.draft_parts = []
    u.undo_stack = []


def _drafts_map(user_id: int) -> Dict[str, Dict[str, Any]]:
    u = users_data.get(user_id)
    if u is None:
        return {}
    if not isinstance(u.drafts, dict):
        u.drafts = {}
    return u.drafts


def _gen_draft_id(existing: Set[str]) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    while True:
        n = secrets.randbits(40)
        s = ""
        while n:
            n, r = divmod(n, 36)
            s = alphabet[r] + s
        if not s:
            s = "0"
        draft_id = s[:8] if len(s) >= 8 else s.rjust(8, "0")
        if draft_id not in existing:
            return draft_id


def _draft_title_for_save(title: str, parts: List[str]) -> str:
    if title.strip():
        return title.strip()
    for part in parts:
        line = (part or "").strip()
        if line:
            return line[:80]
    return "Untitled draft"


def _active_draft_data(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[str, List[str]]:
    title = context.user_data.get(K_TITLE) or users_data.get(user_id, UserData(api_key="")).draft_title
    parts = get_draft_parts(context)
    if not parts:
        parts = list(users_data.get(user_id, UserData(api_key="")).draft_parts or [])
    return str(title or ""), list(parts or [])


def _has_active_draft(title: str, parts: List[str]) -> bool:
    return bool((title or "").strip() or any((p or "").strip() for p in parts))


def _save_draft_snapshot(user_id: int, title: str, parts: List[str]) -> Optional[str]:
    if not _has_active_draft(title, parts):
        return None
    drafts = _drafts_map(user_id)
    draft_id = _gen_draft_id(set(drafts.keys()))
    now_ts = time.time()
    drafts[draft_id] = {
        "title": _draft_title_for_save(title, parts),
        "parts": list(parts),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated_ts": now_ts,
    }
    if DRAFTS_MAX and len(drafts) > DRAFTS_MAX:
        # Drop oldest drafts by updated_ts
        ordered = sorted(drafts.items(), key=lambda item: item[1].get("updated_ts", 0.0))
        while len(ordered) > DRAFTS_MAX:
            did, _ = ordered.pop(0)
            drafts.pop(did, None)
    return draft_id


def _set_active_draft(
    user_id: int, context: ContextTypes.DEFAULT_TYPE, title: str, parts: List[str]
) -> None:
    context.user_data[K_TITLE] = title
    set_draft_parts(context, parts)
    context.user_data[K_UNDO_STACK] = list(parts)
    u = users_data[user_id]
    u.draft_title = title
    u.draft_parts = list(parts)
    u.undo_stack = list(parts)
async def gate_callback(query: Any, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Apply cooldown gating for callback queries and answer consistently."""
    if not cooldown_ok(context):
        try:
            await query.answer(MESSAGES["PLEASE_WAIT"], show_alert=False)
        except Exception:
            pass
        return False
    try:
        await query.answer()
    except Exception:
        pass
    return True
