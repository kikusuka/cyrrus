"""
Tests for the synchronous process_sync wrapper.
"""
import asyncio
import sqlite3

import pytest

from cyrrus import Projector


def _llm():
    async def llm(messages):
        return "ok"
    return llm


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


def test_process_sync_two_calls_share_memory(tmp_path):
    """Two successive process_sync calls share memory via the same background loop."""
    db_path = str(tmp_path / "sync_share.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    # First call stores a fact (wait for extraction via flush_sync)
    bot.process_sync("my name is Alice", session_id="s1")
    bot.flush_sync()
    assert _fact_stored(db_path, "s1") == "Alice"

    # Second call can retrieve the fact
    bot.process_sync("what is my name", session_id="s1")
    bot.close_sync()


def test_process_sync_repeated_calls_same_projector(tmp_path):
    """Repeated process_sync calls on the same Projector all work."""
    db_path = str(tmp_path / "sync_repeat.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    for i in range(3):
        reply = bot.process_sync(f"turn {i}", session_id="s1")
        assert isinstance(reply, str)
    bot.flush_sync()
    bot.close_sync()


def test_process_sync_inside_running_loop_raises(tmp_path):
    """Calling process_sync from inside a running event loop raises RuntimeError."""
    db_path = str(tmp_path / "sync_loop.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )

    async def inner():
        with pytest.raises(RuntimeError, match="use await process\(\) instead"):
            bot.process_sync("hello", session_id="s1")

    asyncio.run(inner())
    bot.close_sync()


def test_process_sync_stores_fact(tmp_path):
    """process_sync stores facts (via flush_sync)."""
    db_path = str(tmp_path / "sync_store.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    bot.process_sync("my name is Alice", session_id="s1")
    bot.flush_sync()
    assert _fact_stored(db_path, "s1") == "Alice"
    bot.close_sync()


def test_close_sync_stops_thread(tmp_path):
    """close_sync stops the background thread."""
    db_path = str(tmp_path / "sync_close.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    bot.process_sync("hello", session_id="s1")
    assert bot._sync_thread is not None
    assert bot._sync_thread.is_alive()
    bot.close_sync()
    assert bot._sync_loop is None
    assert bot._sync_thread is None