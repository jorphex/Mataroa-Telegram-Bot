import json

import pytest

import storage
from constants import DEFAULT_PREVIEW_LENGTH


@pytest.fixture(autouse=True)
def clear_users():
    storage.users_data.clear()
    yield
    storage.users_data.clear()


@pytest.mark.asyncio
async def test_load_users_data_sanitizes_malformed_user_fields(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    users_path = state_dir / "users.json"
    state_dir.mkdir()
    users_path.write_text(
        json.dumps(
            {
                "users": {
                    "42": {
                        "api_key": "key",
                        "published_at": 123,
                        "draft_parts": "not-a-list",
                        "undo_stack": {"bad": "shape"},
                        "last_action": ["bad"],
                        "settings": {
                            "default_publish_mode": "surprise",
                            "preview_length": 999,
                            "preview_format": "html",
                            "confirm_before_delete": True,
                        },
                    }
                }
            }
        )
    )
    monkeypatch.setattr(storage, "CONFIG_DIR", str(state_dir))
    monkeypatch.setattr(storage, "USERS_JSON_PATH", str(users_path))

    await storage.load_users_data()

    user = storage.users_data[42]
    assert user.published_at is None
    assert user.draft_parts == []
    assert user.undo_stack == []
    assert user.last_action == {}
    assert user.settings == {
        "default_publish_mode": "draft",
        "preview_length": DEFAULT_PREVIEW_LENGTH,
        "preview_format": "markdown",
        "confirm_before_delete": True,
    }
