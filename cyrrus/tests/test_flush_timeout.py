"""
Item 2: flush() (and therefore ask()) must not block forever on a fact
extraction that never finishes. flush() gains a bounded wait (flush_timeout,
default 10s, configurable). On timeout it logs a warning and returns normally
so ask() still returns the model reply -- it must not raise.

Pre-fix these fail: Projector has no flush_timeout kwarg (TypeError), and the
old flush() awaits asyncio.gather with no bound, so a never-finishing extractor
would hang ask() forever.
"""
import asyncio
import logging
import time

from cyrrus import Projector


def _llm():
    async def llm(messages):
        return "ok"
    return llm


def _never_finishing_extractor():
    async def extract(text):
        # Bound to the running loop; never set, but cancellable.
        await asyncio.Event().wait()
        return {"user_name": "Alice"}  # pragma: no cover - never reached
    return extract


def test_flush_timeout_defaults_to_10s(tmp_path):
    bot = Projector.minimal(
        llm_call=_llm(),
        fact_extractor=_never_finishing_extractor(),
        memory_db_path=str(tmp_path / "d.db"),
    )
    assert bot.flush_timeout == 10.0


def test_flush_timeout_is_configurable(tmp_path):
    bot = Projector.minimal(
        llm_call=_llm(),
        fact_extractor=_never_finishing_extractor(),
        memory_db_path=str(tmp_path / "c.db"),
        flush_timeout=0.25,
    )
    assert bot.flush_timeout == 0.25


def test_ask_returns_reply_when_extraction_hangs(tmp_path, caplog):
    """ask() must return the reply within the bounded flush wait, not hang."""
    db_path = str(tmp_path / "hang.db")
    bot = Projector.minimal(
        llm_call=_llm(),
        fact_extractor=_never_finishing_extractor(),
        memory_db_path=db_path,
        flush_timeout=0.3,
    )
    start = time.time()
    with caplog.at_level(logging.WARNING, logger="cyrrus.projector"):
        reply = bot.ask("my name is Alice", session_id="s1")
    elapsed = time.time() - start

    assert reply == "ok"
    # Bounded: the 0.3s flush timeout plus slack, nowhere near a hang.
    assert elapsed < 5.0, "ask() appears to hang: %.2fs" % elapsed
    # A warning was logged about extraction not completing; nothing raised.
    assert any(
        "extraction" in r.getMessage().lower() for r in caplog.records
    ), "expected a warning about extraction not completing"
