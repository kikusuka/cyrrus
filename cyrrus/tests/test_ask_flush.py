"""
STEP 1 regression test (deterministic): Projector.ask() must store extracted
facts before returning.

ask() is the sync wrapper asyncio.run(process(...)). process() schedules fact
extraction as a background asyncio task (fire-and-forget when
wait_for_extraction=False). The pre-fix ask() never awaited it, and asyncio.run
closes the loop the moment process() returns -- cancelling the still-pending
task -- so the turn's facts were lost.

Why this test is deterministic (no sleeps, no scheduler races):

  * The extractor is *gated*: it sets `started` and then blocks on `release`
    (awaited via asyncio.to_thread so it never blocks the event loop).
  * The test releases the gate ONLY after `started` fires, i.e. only once the
    extraction task is actually running.
  * On the PRE-FIX code the extraction task never runs at all: after
    create_task, process() only awaits an immediate llm_call (no loop yield) and
    returns, so asyncio.run cancels the task before its first line executes.
    Therefore `started` is never set and the fact is never stored -> the asserts
    below fail on 100% of runs.
  * On the FIXED code ask() awaits flush(), which awaits the pending extraction
    task; it runs, sets `started`, the test sets `release`, extraction finishes,
    and the fact is stored before ask() returns -> passes on 100% of runs.
"""
import sqlite3
import threading

import asyncio

from cyrrus import Projector

_GATE_TIMEOUT = 3.0


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


def _run_gated_ask(db_path, session_id):
    """Drive ask() on a worker thread with a gated extractor.

    Returns (reply, started_fired). The gate is released only after the
    extraction task signals it has started, so the extraction can never complete
    before ask() would naturally return.
    """
    started = threading.Event()
    release = threading.Event()

    async def llm(messages):
        return "ok"

    async def gated_extractor(text):
        started.set()
        # Block without stalling ask()'s event loop; released by the test thread.
        await asyncio.to_thread(release.wait, _GATE_TIMEOUT)
        if "my name is" in text:
            return {"user_name": "Alice"}
        return {}

    bot = Projector.minimal(
        llm_call=llm,
        fact_extractor=gated_extractor,
        memory_db_path=db_path,
    )

    box = {}

    def worker():
        box["reply"] = bot.ask("my name is Alice", session_id=session_id)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # Only release extraction once it has actually begun running. On pre-fix
    # code this wait times out because the task is cancelled before it starts.
    started_fired = started.wait(_GATE_TIMEOUT)
    release.set()
    t.join(_GATE_TIMEOUT + 5.0)
    return box.get("reply"), started_fired, t.is_alive()


def test_ask_stores_gated_facts_before_returning(tmp_path):
    db_path = str(tmp_path / "ask_gated.db")
    reply, started_fired, still_alive = _run_gated_ask(db_path, "s1")

    # ask() must have returned (worker thread finished).
    assert not still_alive, "ask() did not return"
    assert reply == "ok"
    # Extraction must have actually run (it never does on the pre-fix code).
    assert started_fired, "extraction task never ran (cancelled before start)"
    # And its fact must be persisted before ask() returned.
    assert _fact_stored(db_path, "s1") == "Alice"
