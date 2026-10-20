"""
Tests for forget_fact, forget_session, and export_facts data control.
"""
import asyncio
import sqlite3

import pytest

from cyrrus import Projector
from cyrrus.backend import MemoryBackend
from cyrrus.memory import MemoryVault
from cyrrus.sqlite_backend import SQLiteBackend


def _llm():
    async def llm(messages):
        return "ok"
    return llm


@pytest.mark.asyncio
async def test_forget_fact_deletes_all_versions(tmp_path):
    """forget_fact physically deletes ALL rows for (session, key), including superseded."""
    db_path = str(tmp_path / "forget_fact.db")
    memory = MemoryVault(db_path=db_path)
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "user_name", "Bob", 2)  # supersedes Alice
    # Both versions exist
    history = await memory.get_fact_history("s1", "user_name")
    assert len(history) == 2
    # Forget the fact
    result = await memory.forget_fact("s1", "user_name")
    assert result is True
    # No current fact remains
    rows = await memory._backend.retrieve_current("s1")
    assert len(rows) == 0
    # No history remains either
    history = await memory.get_fact_history("s1", "user_name")
    assert len(history) == 0


@pytest.mark.asyncio
async def test_forget_fact_returns_false_when_nothing_deleted(tmp_path):
    """forget_fact returns False when no rows exist for the key."""
    db_path = str(tmp_path / "forget_fact_none.db")
    memory = MemoryVault(db_path=db_path)
    result = await memory.forget_fact("s1", "nonexistent_key")
    assert result is False


@pytest.mark.asyncio
async def test_forget_session_deletes_all_facts(tmp_path):
    """forget_session deletes all facts for a session."""
    db_path = str(tmp_path / "forget_session.db")
    memory = MemoryVault(db_path=db_path)
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "user_city", "Lisbon", 2)
    await memory.upsert("s2", "user_name", "Bob", 2)  # different session, untouched

    count = await memory.forget_session("s1")
    assert count == 2

    rows_s1 = await memory._backend.retrieve_current("s1")
    assert len(rows_s1) == 0
    rows_s2 = await memory._backend.retrieve_current("s2")
    assert len(rows_s2) == 1  # s2 unaffected
    assert rows_s2[0] == ("user_name", "Bob", 2)


@pytest.mark.asyncio
async def test_forget_session_new_projector_cannot_see_facts(tmp_path):
    """After forget_session, a NEW Projector on the same DB no longer finds the facts."""
    db_path = str(tmp_path / "forget_new_proj.db")

    # First projector: store facts
    bot1 = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    await bot1.process("my name is Alice", session_id="s1", wait_for_extraction=True)
    await bot1.flush()

    # Forget the session
    count = await bot1.forget_session("s1")
    assert count >= 1

    # Second projector on same DB: facts should be gone
    bot2 = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    slides = await bot2.memory.retrieve("s1", "what is my name", limit=3)
    assert len(slides) == 0


@pytest.mark.asyncio
async def test_export_facts_current_only(tmp_path):
    """export_facts returns only current facts by default."""
    db_path = str(tmp_path / "export.db")
    memory = MemoryVault(db_path=db_path)
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "user_name", "Bob", 2)  # supersedes Alice

    facts = await memory.export_facts("s1")
    assert len(facts) == 1
    assert facts[0]["key"] == "user_name"
    assert facts[0]["value"] == "Bob"
    assert "created" in facts[0]
    assert "invalid_at" in facts[0]
    assert facts[0]["invalid_at"] is None  # current fact


@pytest.mark.asyncio
async def test_export_facts_include_superseded(tmp_path):
    """export_facts(include_superseded=True) returns all versions."""
    db_path = str(tmp_path / "export_sup.db")
    memory = MemoryVault(db_path=db_path)
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "user_name", "Bob", 2)

    facts = await memory.export_facts("s1", include_superseded=True)
    assert len(facts) == 2
    # Ordered by creation: Alice first, then Bob
    assert facts[0]["value"] == "Alice"
    assert facts[1]["value"] == "Bob"
    assert facts[0]["invalid_at"] is not None  # superseded
    assert facts[1]["invalid_at"] is None  # current


@pytest.mark.asyncio
async def test_export_facts_ordered_by_creation(tmp_path):
    """export_facts returns facts ordered by creation."""
    db_path = str(tmp_path / "export_order.db")
    memory = MemoryVault(db_path=db_path)
    await memory.upsert("s1", "user_city", "Lisbon", 2)
    await memory.upsert("s1", "user_name", "Alice", 2)

    facts = await memory.export_facts("s1")
    assert len(facts) == 2
    assert facts[0]["key"] == "user_city"
    assert facts[1]["key"] == "user_name"


@pytest.mark.asyncio
async def test_custom_backend_forget_fact_raises_not_implemented():
    """A custom backend without forget_fact raises NotImplementedError."""

    class NoForgetBackend(MemoryBackend):
        async def init_db(self): pass
        async def upsert(self, session_id, keyword, value, tokens, max_facts_per_session, max_fact_value_length): pass
        async def retrieve_current(self, session_id, limit=100): return []
        async def touch(self, session_id, keywords): pass
        async def delete_session(self, session_id): return 0
        async def get_fact_history(self, session_id, keyword): return []
        async def close(self): pass

    backend = NoForgetBackend()
    with pytest.raises(NotImplementedError, match="forget_fact"):
        await backend.forget_fact("s1", "user_name")


@pytest.mark.asyncio
async def test_custom_backend_forget_session_raises_not_implemented():
    """A custom backend without forget_session raises NotImplementedError."""

    class NoForgetBackend(MemoryBackend):
        async def init_db(self): pass
        async def upsert(self, session_id, keyword, value, tokens, max_facts_per_session, max_fact_value_length): pass
        async def retrieve_current(self, session_id, limit=100): return []
        async def touch(self, session_id, keywords): pass
        async def delete_session(self, session_id): return 0
        async def get_fact_history(self, session_id, keyword): return []
        async def close(self): pass

    backend = NoForgetBackend()
    with pytest.raises(NotImplementedError, match="forget_session"):
        await backend.forget_session("s1")


@pytest.mark.asyncio
async def test_custom_backend_export_facts_raises_not_implemented():
    """A custom backend without export_facts raises NotImplementedError."""

    class NoExportBackend(MemoryBackend):
        async def init_db(self): pass
        async def upsert(self, session_id, keyword, value, tokens, max_facts_per_session, max_fact_value_length): pass
        async def retrieve_current(self, session_id, limit=100): return []
        async def touch(self, session_id, keywords): pass
        async def delete_session(self, session_id): return 0
        async def get_fact_history(self, session_id, keyword): return []
        async def close(self): pass

    backend = NoExportBackend()
    with pytest.raises(NotImplementedError, match="export_facts"):
        await backend.export_facts("s1")


@pytest.mark.asyncio
async def test_projector_forget_fact_delegates(tmp_path):
    """Projector.forget_fact delegates to MemoryVault."""
    db_path = str(tmp_path / "proj_forget.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    await bot.memory.upsert("s1", "user_name", "Alice", 2)
    await bot.memory.upsert("s1", "user_name", "Bob", 2)

    result = await bot.forget_fact("s1", "user_name")
    assert result is True
    rows = await bot.memory.retrieve("s1", "anything", limit=3)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_projector_forget_session_clears_tray_and_history(tmp_path):
    """Projector.forget_session clears tray and history for the session."""
    db_path = str(tmp_path / "proj_forget_session.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    await bot.memory.upsert("s1", "user_name", "Alice", 2)
    # Force tray/history creation
    await bot._get_tray("s1")
    await bot._get_history("s1")
    assert "s1" in bot.trays
    assert "s1" in bot._histories

    count = await bot.forget_session("s1")
    assert count >= 1
    assert "s1" not in bot.trays
    assert "s1" not in bot._histories


@pytest.mark.asyncio
async def test_projector_export_facts_delegates(tmp_path):
    """Projector.export_facts delegates to MemoryVault."""
    db_path = str(tmp_path / "proj_export.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=_llm(),
        memory_db_path=db_path,
    )
    await bot.memory.upsert("s1", "user_name", "Alice", 2)

    facts = await bot.export_facts("s1")
    assert len(facts) == 1
    assert facts[0]["key"] == "user_name"
    assert facts[0]["value"] == "Alice"


def test_sqlite_backend_forget_and_export(tmp_path):
    """SQLiteBackend forget_fact, forget_session, export_facts work synchronously via asyncio.run."""
    db_path = str(tmp_path / "sqlite_forget.db")

    async def run():
        backend = SQLiteBackend(db_path)
        await backend.init_db()

        await backend.upsert("s1", "user_name", "Alice", 1, None, 500)
        await backend.upsert("s1", "user_name", "Bob", 1, None, 500)
        await backend.upsert("s1", "user_city", "Lisbon", 1, None, 500)

        # forget_fact
        assert await backend.forget_fact("s1", "user_name") is True
        current = await backend.retrieve_current("s1")
        assert len(current) == 1
        assert current[0][0] == "user_city"

        # export_facts current only
        facts = await backend.export_facts("s1")
        assert len(facts) == 1
        assert facts[0]["key"] == "user_city"
        assert facts[0]["value"] == "Lisbon"

        # forget_session
        count = await backend.forget_session("s1")
        assert count == 1
        current = await backend.retrieve_current("s1")
        assert len(current) == 0

        await backend.close()

    asyncio.run(run())