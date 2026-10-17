"""
Tests for the wait_for_extraction option on Projector.process() and
aprocess_stream().

These tests fail on the old behavior: the old Projector does not accept
wait_for_extraction anywhere, so every call passing it raises TypeError.
"""
import asyncio
import sqlite3

import pytest

from cyrrus import Projector
from cyrrus.providers import StreamChunk


def _llm():
    async def llm(messages):
        return "ok"
    return llm


def _slow_extractor(delay: float = 0.3):
    async def extract(text):
        await asyncio.sleep(delay)
        if "my name is" in text:
            return {"user_name": "Alice"}
        return {}
    return extract


def _fact_stored(db_path: str, session_id: str, keyword: str = "user_name"):
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM facts WHERE session_id=? AND keyword=? "
                "AND invalid_at IS NULL",
                (session_id, keyword),
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return row[0] if row is not None else None


@pytest.mark.asyncio
async def test_wait_for_extraction_true_stores_fact_immediately(tmp_path):
    """With wait_for_extraction=True, the fact is stored when process() returns."""
    db_path = str(tmp_path / "true.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        fact_extractor=_slow_extractor(0.3),
        memory_db_path=db_path,
    )
    await bot.process("my name is Alice", session_id="s1", wait_for_extraction=True)
    assert _fact_stored(db_path, "s1") == "Alice"


@pytest.mark.asyncio
async def test_wait_for_extraction_false_not_guaranteed_immediately(tmp_path):
    """With wait_for_extraction=False, the fact is NOT stored when process() returns."""
    db_path = str(tmp_path / "false.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        fact_extractor=_slow_extractor(0.3),
        memory_db_path=db_path,
    )
    await bot.process("my name is Alice", session_id="s2", wait_for_extraction=False)
    assert _fact_stored(db_path, "s2") is None


@pytest.mark.asyncio
async def test_constructor_true_call_false_no_wait(tmp_path):
    """Constructor True + per-call False => fire-and-forget, not stored immediately."""
    db_path = str(tmp_path / "ctor_true.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        fact_extractor=_slow_extractor(0.3),
        memory_db_path=db_path,
        wait_for_extraction=True,
    )
    await bot.process("my name is Alice", session_id="s3", wait_for_extraction=False)
    assert _fact_stored(db_path, "s3") is None


@pytest.mark.asyncio
async def test_constructor_false_call_true_waits(tmp_path):
    """Constructor False + per-call True => awaits, fact stored when returns."""
    db_path = str(tmp_path / "ctor_false.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        fact_extractor=_slow_extractor(0.3),
        memory_db_path=db_path,
    )
    await bot.process("my name is Alice", session_id="s4", wait_for_extraction=True)
    assert _fact_stored(db_path, "s4") == "Alice"


@pytest.mark.asyncio
async def test_streaming_wait_for_extraction_true_stores_fact(tmp_path):
    """Streaming with wait_for_extraction=True stores facts after the stream completes."""
    db_path = str(tmp_path / "stream.db")

    llm = _llm()

    async def astream(messages):
        yield StreamChunk(text="hello", finish_reason=None, usage=None)
        yield StreamChunk(text=" world", finish_reason="stop", usage={"total_tokens": 2})

    llm.astream = astream

    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=llm,
        fact_extractor=_slow_extractor(0.3),
        memory_db_path=db_path,
    )
    async for _ in bot.aprocess_stream(
        "my name is Alice", session_id="s5", wait_for_extraction=True
    ):
        pass
    assert _fact_stored(db_path, "s5") == "Alice"
