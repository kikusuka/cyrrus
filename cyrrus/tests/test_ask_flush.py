"""
STEP 1 regression tests: Projector.ask() must store extracted facts before
returning.

ask() is the sync convenience wrapper (asyncio.run(process(...))). The pipeline
schedules fact extraction as a background asyncio task (fire-and-forget when
wait_for_extraction=False). asyncio.run() closes the loop as soon as process()
returns, cancelling that pending task, so facts were lost. These tests fail on
the old behavior and pass once ask() flushes pending extractions before
returning.
"""
import sqlite3

from cyrrus import Projector


def _llm():
    async def llm(messages):
        return "ok"
    return llm


def _extractor():
    async def extract(text):
        if "my name is" in text:
            return {"user_name": "Alice"}
        return {}
    return extract


def _fact_stored(db_path, session_id, keyword="user_name"):
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


def test_ask_stores_facts_before_returning(tmp_path):
    """ask() must persist the turn's facts before it returns."""
    db_path = str(tmp_path / "ask.db")
    bot = Projector.minimal(
        llm_call=_llm(),
        fact_extractor=_extractor(),
        memory_db_path=db_path,
    )
    reply = bot.ask("my name is Alice", session_id="s1")
    assert reply == "ok"
    assert _fact_stored(db_path, "s1") == "Alice"


def test_ask_stores_facts_across_sequential_calls(tmp_path):
    """Repeated ask() calls each persist their facts."""
    db_path = str(tmp_path / "ask_seq.db")
    bot = Projector.minimal(
        llm_call=_llm(),
        fact_extractor=_extractor(),
        memory_db_path=db_path,
    )
    bot.ask("my name is Alice", session_id="s2")
    bot.ask("nothing memorable here", session_id="s2")
    assert _fact_stored(db_path, "s2") == "Alice"
