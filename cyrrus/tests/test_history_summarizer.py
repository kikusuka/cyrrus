"""
Tests for the pluggable history summarizer (Projector(history_summarizer=...)).

When history exceeds the verbatim budget, older turns are replaced by a
single summary message built from the summarizer's return value. history_summarizer=None
keeps today's behavior exactly.
"""
import asyncio
import time

import pytest

from cyrrus import Projector
from cyrrus.projector import _build_compact_history


def base_config():
    return {"core_lamp": {"content": "You are helpful."}}


def make_bot(captured, tmp_path, **kwargs):
    async def llm_call(messages):
        captured.append(messages)
        return "ok"

    bot = Projector(
        base_config(),
        llm_call=llm_call,
        history_window=10,
        history_verbatim_turns=2,
        memory_db_path=str(tmp_path / "hist.db"),
        **kwargs,
    )
    return bot


MEMORY_MSG = "My name is Alice and I always drink coffee."


async def _run_turns(bot, count=5, session_id="s1"):
    for i in range(count):
        await bot.process(f"turn {i}: {MEMORY_MSG}", session_id=session_id)


def _last_history_messages(captured):
    return captured[-1]


@pytest.mark.asyncio
async def test_custom_summarizer_called_with_old_messages_and_text_appears(tmp_path):
    captured = []
    seen = []

    async def summarizer(old_messages):
        seen.append([dict(m) for m in old_messages])
        return "Alice likes coffee and prefers it black."

    bot = make_bot(captured, tmp_path, history_summarizer=summarizer)
    await _run_turns(bot)

    assert seen, "summarizer must be called with the old messages"
    old = seen[-1]
    assert all(m["role"] in ("user", "assistant") for m in old)
    assert all("content" in m for m in old)

    messages = _last_history_messages(captured)
    summary_msgs = [
        m for m in messages if m["role"] == "system" and "Alice likes coffee" in m["content"]
    ]
    assert summary_msgs, "summarizer text must appear in the prompt"


@pytest.mark.asyncio
async def test_none_summarizer_is_unchanged(tmp_path):
    captured = []
    bot = make_bot(captured, tmp_path)  # history_summarizer defaults to None
    await _run_turns(bot)

    # history is appended to after llm_call returns, so reconstruct the
    # history as it was when the last turn's messages were captured.
    history = await bot._get_history("s1")
    prepare_history = list(history)[:-2]
    expected = _build_compact_history(prepare_history, bot.history_verbatim_turns)

    messages = _last_history_messages(captured)
    # [system] + compact history + [user]
    assert messages[1:-1] == expected, "history_summarizer=None must behave exactly as today"


@pytest.mark.asyncio
async def test_async_summarizer(tmp_path):
    captured = []

    async def summarizer(old_messages):
        await asyncio.sleep(0)
        return "async summary of the older turns."

    bot = make_bot(captured, tmp_path, history_summarizer=summarizer)
    await _run_turns(bot)

    messages = _last_history_messages(captured)
    summary_msgs = [
        m for m in messages if m["role"] == "system" and "async summary" in m["content"]
    ]
    assert summary_msgs, "async summarizer text must appear in the prompt"


@pytest.mark.asyncio
async def test_sync_summarizer(tmp_path):
    captured = []

    def summarizer(old_messages):
        return "sync summary of the older turns."

    bot = make_bot(captured, tmp_path, history_summarizer=summarizer)
    await _run_turns(bot)

    messages = _last_history_messages(captured)
    summary_msgs = [
        m for m in messages if m["role"] == "system" and "sync summary" in m["content"]
    ]
    assert summary_msgs, "sync summarizer text must appear in the prompt"


@pytest.mark.asyncio
async def test_raising_summarizer_falls_back_and_never_crashes(tmp_path):
    captured = []

    def summarizer(old_messages):
        raise RuntimeError("summarizer boom")

    bot = make_bot(captured, tmp_path, history_summarizer=summarizer)
    response = await _run_turns_and_return(bot)

    assert response == "ok", "turn must not crash when the summarizer raises"

    messages = _last_history_messages(captured)
    fallback = [
        m for m in messages if m["role"] == "system" and "Previously mentioned" in m["content"]
    ]
    assert fallback, "must fall back to today's built-in compression"


@pytest.mark.asyncio
async def test_timing_out_summarizer_falls_back_and_never_crashes(tmp_path):
    captured = []

    async def slow_summarizer(old_messages):
        await asyncio.sleep(60)
        return "never arrives"

    bot = make_bot(
        captured, tmp_path, history_summarizer=slow_summarizer, summarizer_timeout=0.05
    )

    start = time.time()
    response = await _run_turns_and_return(bot)
    elapsed = time.time() - start

    assert response == "ok", "turn must not crash when the summarizer times out"
    assert elapsed < 5, "summarizer timeout must not hang the turn"

    messages = _last_history_messages(captured)
    fallback = [
        m for m in messages if m["role"] == "system" and "Previously mentioned" in m["content"]
    ]
    assert fallback, "must fall back to today's built-in compression on timeout"


async def _run_turns_and_return(bot, count=5, session_id="s1"):
    for i in range(count):
        response = await bot.process(f"turn {i}: {MEMORY_MSG}", session_id=session_id)
    return response
