from types import SimpleNamespace

import httpx
import pytest

import handlers as h
from constants import (
    ENTER_BODY,
    ENTER_PUBLISH_CHOICE_UPDATE,
    ENTER_TITLE,
    K_BODY,
    K_BODY_PARTS,
    K_TITLE,
    K_UNDO_STACK,
)
from storage import UserData, users_data


class FakeMessage:
    def __init__(self, text, user_id=1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(chat_id=10, message_id=20)


class FakeQuery:
    def __init__(self, user_id=1):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat_id=10, message_id=20)
        self.edits = []

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeContext:
    def __init__(self):
        self.user_data = {}
        self.application = SimpleNamespace(user_data={})


class MarkdownRaisesMessage:
    text = "plain fallback"
    entities = [object()]

    @property
    def text_markdown(self):
        raise ValueError("unsupported entity")

    @property
    def text_markdown_v2(self):
        raise ValueError("unsupported entity")


@pytest.fixture(autouse=True)
def clear_users():
    users_data.clear()
    h.allowed_user_ids.cache_clear()
    yield
    h.allowed_user_ids.cache_clear()
    users_data.clear()


def test_extract_message_text_falls_back_when_markdown_rendering_fails():
    assert h.extract_message_text(MarkdownRaisesMessage()) == "plain fallback"


def test_allowed_user_ids_ignores_bad_entries_and_caches(monkeypatch):
    h.allowed_user_ids.cache_clear()
    monkeypatch.setenv("MATAROA_BOT_ALLOWED_USERS", "1,bad, 2")

    assert h.allowed_user_ids() == {1, 2}

    monkeypatch.setenv("MATAROA_BOT_ALLOWED_USERS", "3")
    assert h.allowed_user_ids() == {1, 2}
    h.allowed_user_ids.cache_clear()


@pytest.mark.asyncio
async def test_enter_body_preserves_user_whitespace(monkeypatch):
    async def save_noop(context):
        return None

    monkeypatch.setattr(h, "schedule_users_data_save", save_noop)
    users_data[1] = UserData(api_key="key", draft_title="Title")
    context = FakeContext()
    update = SimpleNamespace(message=FakeMessage("  indented\n\n", user_id=1))

    result = await h.enter_body(update, context)

    assert result == ENTER_BODY
    assert context.user_data[K_BODY_PARTS] == ["  indented\n\n"]
    assert users_data[1].draft_parts == ["  indented\n\n"]


@pytest.mark.asyncio
async def test_enter_updated_body_preserves_user_whitespace():
    users_data[1] = UserData(api_key="key")
    context = FakeContext()
    update = SimpleNamespace(message=FakeMessage("\n# Heading\n", user_id=1))

    result = await h.enter_updated_body(update, context)

    assert result == ENTER_PUBLISH_CHOICE_UPDATE
    assert context.user_data[K_BODY] == "\n# Heading\n"


@pytest.mark.asyncio
async def test_draft_clear_clears_title_body_and_persistent_resume(monkeypatch):
    async def save_noop(context):
        return None

    monkeypatch.setattr(h, "schedule_users_data_save", save_noop)
    users_data[1] = UserData(
        api_key="key",
        draft_title="Stale title",
        draft_parts=["body"],
        undo_stack=["body"],
    )
    context = FakeContext()
    context.user_data.update(
        {K_TITLE: "Stale title", K_BODY_PARTS: ["body"], K_UNDO_STACK: ["body"]}
    )
    update = SimpleNamespace(message=FakeMessage("/clear", user_id=1))

    result = await h.draft_clear(update, context)

    assert result == ENTER_TITLE
    assert K_TITLE not in context.user_data
    assert context.user_data[K_BODY_PARTS] == []
    assert users_data[1].draft_title == ""
    assert users_data[1].draft_parts == []
    assert "Enter the title" in update.message.replies[-1][0]


@pytest.mark.asyncio
async def test_submit_create_success_clears_context_and_persistent_draft(monkeypatch):
    async def save_noop():
        return None

    async def api_call_noop(*args, **kwargs):
        return httpx.Response(200), {
            "ok": True,
            "slug": "new-post",
            "url": "https://example.com/blog/new-post/",
        }

    monkeypatch.setattr(h, "save_users_data", save_noop)
    monkeypatch.setattr(h, "api_call", api_call_noop)
    users_data[1] = UserData(
        api_key="key",
        draft_title="Title",
        draft_parts=["body"],
        undo_stack=["body"],
        last_action={"type": "create"},
    )
    context = FakeContext()
    context.user_data.update(
        {
            K_TITLE: "Title",
            K_BODY: "body",
            K_BODY_PARTS: ["body"],
            K_UNDO_STACK: ["body"],
        }
    )
    query = FakeQuery(user_id=1)

    await h._submit_create_post(query, context)

    assert K_TITLE not in context.user_data
    assert K_BODY not in context.user_data
    assert context.user_data[K_BODY_PARTS] == []
    assert users_data[1].draft_title == ""
    assert users_data[1].draft_parts == []
    assert users_data[1].last_action == {}
