import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from constants import (
    ALLOWED_PREVIEW_FORMATS,
    ALLOWED_PREVIEW_LENGTHS,
    DEFAULT_PREVIEW_LENGTH,
    DRAFTS_MAX,
)

logger = logging.getLogger(__name__)

# Repo-local state dir and users.json path
CONFIG_DIR = os.getenv(
    "MATAROA_BOT_DIR", str(Path(__file__).resolve().parent / ".state")
)
USERS_JSON_PATH = os.path.join(CONFIG_DIR, "users.json")

users_data: Dict[int, "UserData"] = {}  # user_id -> UserData
_users_data_lock: Optional[asyncio.Lock] = None


@dataclass
class UserData:
    api_key: str
    title: str = ""
    body: str = ""
    published_at: Optional[str] = None
    draft_title: str = ""
    draft_parts: List[str] = field(default_factory=list)
    drafts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    undo_stack: List[str] = field(default_factory=list)
    last_action: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(
        default_factory=lambda: {
            "default_publish_mode": "draft",  # draft|publish
            "preview_length": DEFAULT_PREVIEW_LENGTH,
            "preview_format": "markdown",  # markdown|plain
            "confirm_before_delete": True,
        }
    )


def _get_users_data_lock() -> asyncio.Lock:
    global _users_data_lock
    if _users_data_lock is None:
        _users_data_lock = asyncio.Lock()
    return _users_data_lock


# ---------- Secure Config Helpers ----------
async def ensure_config_dir() -> None:
    """Ensure the config directory exists with secure permissions where possible."""
    try:
        Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(CONFIG_DIR, 0o700)
        except Exception:
            pass
    except Exception as e:
        logger.error("Failed to ensure config dir: %s", e)


def enforce_config_permissions() -> None:
    """Enforce secure permissions on config dir and users.json (raise on fatal errors)."""
    if os.name != "posix":
        try:
            Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create config dir: %s", e)
        logger.warning(
            "Skipping strict permission enforcement on non-POSIX platform: %s", os.name
        )
        return
    try:
        Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("Failed to create config dir: %s", e)
        raise RuntimeError("Failed to create config directory") from e
    try:
        st = os.stat(CONFIG_DIR)
        mode = st.st_mode & 0o777
        if mode != 0o700:
            try:
                os.chmod(CONFIG_DIR, 0o700)
            except Exception:
                pass
            st2 = os.stat(CONFIG_DIR)
            if (st2.st_mode & 0o777) != 0o700:
                logger.error("Insecure permissions on %s (expected 0700).", CONFIG_DIR)
                raise RuntimeError("Insecure config dir permissions")
    except Exception as e:
        logger.error("Permission check failed for %s: %s", CONFIG_DIR, e)
        raise RuntimeError("Config dir permission check failed") from e
    if os.path.exists(USERS_JSON_PATH):
        try:
            stf = os.stat(USERS_JSON_PATH)
            fmode = stf.st_mode & 0o777
            if fmode != 0o600:
                try:
                    os.chmod(USERS_JSON_PATH, 0o600)
                except Exception:
                    pass
                stf2 = os.stat(USERS_JSON_PATH)
                if (stf2.st_mode & 0o777) != 0o600:
                    logger.error(
                        "Insecure permissions on %s (expected 0600).", USERS_JSON_PATH
                    )
                    raise RuntimeError("Insecure users.json permissions")
        except Exception as e:
            logger.error("Permission check failed for %s: %s", USERS_JSON_PATH, e)
            raise RuntimeError("users.json permission check failed") from e


# ---------- Async File I/O Helpers ----------
async def load_users_data() -> None:
    """Load users.json into memory; tolerate empty/malformed files and warn on parse errors."""
    global users_data
    await ensure_config_dir()
    if os.path.exists(USERS_JSON_PATH):
        try:
            async with aiofiles.open(USERS_JSON_PATH, "r") as f:
                data = await f.read()
        except OSError as e:
            logger.warning("Failed to read %s: %s", USERS_JSON_PATH, e)
            users_data.clear()
            return
        if not data.strip():
            users_data.clear()
            return
        try:
            json_data = json.loads(data)
        except JSONDecodeError as e:
            logger.warning("Failed to parse %s: %s", USERS_JSON_PATH, e)
            users_data.clear()
            return
        # Support both legacy and structured format
        if isinstance(json_data, dict) and "users" in json_data:
            users_json = json_data.get("users", {})
        else:
            users_json = json_data if isinstance(json_data, dict) else {}

        parsed: Dict[int, UserData] = {}
        for k, v in users_json.items():
            try:
                uid = int(k)
            except (TypeError, ValueError):
                continue
            if isinstance(v, str):
                parsed[uid] = UserData(api_key=v)
            elif isinstance(v, dict):
                settings = v.get("settings") if isinstance(v.get("settings"), dict) else {}
                preview_len = settings.get("preview_length", DEFAULT_PREVIEW_LENGTH)
                if not isinstance(preview_len, int) or preview_len not in ALLOWED_PREVIEW_LENGTHS:
                    preview_len = DEFAULT_PREVIEW_LENGTH
                preview_fmt = settings.get("preview_format", "markdown")
                if not isinstance(preview_fmt, str) or preview_fmt not in ALLOWED_PREVIEW_FORMATS:
                    preview_fmt = "markdown"
                raw_drafts = v.get("drafts") if isinstance(v.get("drafts"), dict) else {}
                drafts: Dict[str, Dict[str, Any]] = {}
                if isinstance(raw_drafts, dict):
                    for did, dval in raw_drafts.items():
                        if not isinstance(did, str) or not isinstance(dval, dict):
                            continue
                        title = dval.get("title")
                        parts = dval.get("parts")
                        updated_at = dval.get("updated_at")
                        updated_ts = dval.get("updated_ts")
                        if not isinstance(title, str):
                            title = ""
                        if not isinstance(parts, list):
                            parts = []
                        else:
                            parts = [str(p) for p in parts]
                        if not isinstance(updated_at, str):
                            updated_at = ""
                        if not isinstance(updated_ts, (int, float)):
                            updated_ts = 0.0
                        drafts[did] = {
                            "title": title,
                            "parts": parts,
                            "updated_at": updated_at,
                            "updated_ts": float(updated_ts),
                        }
                if DRAFTS_MAX and len(drafts) > DRAFTS_MAX:
                    ordered = sorted(
                        drafts.items(), key=lambda item: item[1].get("updated_ts", 0.0)
                    )
                    while len(ordered) > DRAFTS_MAX:
                        did, _ = ordered.pop(0)
                        drafts.pop(did, None)
                parsed[uid] = UserData(
                    api_key=str(v.get("api_key", "")),
                    title=str(v.get("title", "")),
                    body=str(v.get("body", "")),
                    published_at=v.get("published_at", None),
                    draft_title=str(v.get("draft_title", "")),
                    draft_parts=v.get("draft_parts", []) or [],
                    drafts=drafts,
                    undo_stack=v.get("undo_stack", []) or [],
                    last_action=v.get("last_action", {}) or {},
                    settings={
                        "default_publish_mode": settings.get("default_publish_mode", "draft")
                        if isinstance(settings, dict)
                        else "draft",
                        "preview_length": preview_len,
                        "preview_format": preview_fmt,
                        "confirm_before_delete": bool(settings.get("confirm_before_delete", True))
                        if isinstance(settings, dict)
                        else True,
                    },
                )
            else:
                parsed[uid] = UserData(api_key="")
        users_data.clear()
        users_data.update(parsed)
    else:
        users_data.clear()


async def save_users_data() -> None:
    await ensure_config_dir()
    async with _get_users_data_lock():
        to_write = {
            "users": {str(k): v.__dict__ for k, v in users_data.items()},
        }
        tmp_path = USERS_JSON_PATH + ".tmp"
        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(json.dumps(to_write, indent=2, sort_keys=True))
        try:
            os.chmod(tmp_path, 0o600)
        except Exception:
            pass
        os.replace(tmp_path, USERS_JSON_PATH)
        try:
            os.chmod(USERS_JSON_PATH, 0o600)
        except Exception:
            pass
