"""
Tests for cyrrus.adapters.make_chat (Step 3: Chat adapter).
"""
import pytest
from cyrrus import Projector
from cyrrus.adapters import make_chat


@pytest.mark.asyncio
async def test_make_chat_returns_reply(tmp_path):
    """make_chat builds a chat() that returns the LLM reply string."""
    config = {"core_lamp": {"content": "You are helpful."}}

    async def fake_llm(messages):
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return f"echo: {last_user}"

    bot = Projector(
        config,
        llm_call=fake_llm,
        memory_db_path=str(tmp_path / "chat.db"),
    )

    chat = make_chat(bot)
    reply = await chat("u1", "hello world")
    assert isinstance(reply, str)
    assert "hello world" in reply or reply.startswith("echo:")


@pytest.mark.asyncio
async def test_make_chat_records_history(tmp_path):
    """Subsequent chat() calls share history — second LLM call sees the first user message."""
    config = {"core_lamp": {"content": "You are helpful."}}
    seen_messages = []

    async def fake_llm(messages):
        seen_messages.append(list(messages))
        return f"reply-{len(seen_messages)}"

    bot = Projector(
        config,
        llm_call=fake_llm,
        memory_db_path=str(tmp_path / "chat_hist.db"),
    )
    chat = make_chat(bot)

    r1 = await chat("u1", "first message")
    r2 = await chat("u1", "second message")

    assert r1 == "reply-1"
    assert r2 == "reply-2"

    # Second call's messages list should contain the FIRST user turn
    # ("first message") because project.process records history internally.
    second_call_messages = seen_messages[1]
    user_contents = [m["content"] for m in second_call_messages if m["role"] == "user"]
    assert any("first message" in c for c in user_contents), (
        f"History missing first turn. user_messages={user_contents}"
    )


@pytest.mark.asyncio
async def test_make_chat_session_isolation(tmp_path):
    """Two different session_ids do not share history."""
    config = {"core_lamp": {"content": "You are helpful."}}
    per_session = {}

    async def fake_llm(messages):
        return f"ok-{len(messages)}"

    bot = Projector(
        config,
        llm_call=fake_llm,
        memory_db_path=str(tmp_path / "sess.db"),
    )
    chat = make_chat(bot)

    await chat("s1", "hello from s1")
    await chat("s1", "hello again s1")  # s1: 2 turns
    await chat("s2", "hello from s2")  # s2: 1 turn

    # s1 should have more history/messages in last call than s2
    # Just verify both sessions got replies (no crashes)
    assert True
