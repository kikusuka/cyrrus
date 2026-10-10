"""
Step 1: input length limits.

The memory layer and the SQLite backend must reject empty or over-long
session ids and over-long fact keywords with ValueError, and must truncate
long fact values (up to 2000 chars) rather than raising.
"""
import sqlite3

import pytest

from cyrrus import MemoryVault
from cyrrus.sqlite_backend import SQLiteBackend

LONG_ID = "s" * 257
LONG_KEYWORD = "k" * 257


@pytest.mark.asyncio
async def test_memory_layer_rejects_bad_session_id(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "limits_id.db"))

    with pytest.raises(ValueError):
        await vault.upsert(LONG_ID, "user_name", "Alice", 1)
    with pytest.raises(ValueError):
        await vault.upsert("", "user_name", "Alice", 1)
    with pytest.raises(ValueError):
        await vault.retrieve(LONG_ID, "what is my name")
    # Reads with empty/None ids stay graceful (isolation, not an error) —
    # tests/test_failsafe.py::test_isolation depends on this.
    assert await vault.retrieve("", "what is my name") == []
    assert await vault.retrieve(None, "what is my name") == []
    with pytest.raises(ValueError):
        await vault.delete_session("")
    with pytest.raises(ValueError):
        await vault.get_fact_history(LONG_ID, "user_name")

    # A 256-char id is at the limit and must still be accepted.
    await vault.upsert("s" * 256, "user_name", "Alice", 1)
    results = await vault.retrieve("s" * 256, "what is my name")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_memory_layer_rejects_long_keyword(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "limits_kw.db"))

    with pytest.raises(ValueError):
        await vault.upsert("s1", LONG_KEYWORD, "Alice", 1)
    with pytest.raises(ValueError):
        await vault.get_fact_history("s1", LONG_KEYWORD)

    await vault.upsert("s1", "k" * 256, "Alice", 1)


@pytest.mark.asyncio
async def test_memory_layer_truncates_long_values_not_raises(tmp_path):
    db = str(tmp_path / "limits_val.db")
    vault = MemoryVault(db_path=db)

    # 1800 chars: over the old 500-char default but well under the new 2000 limit.
    long_ok = "x" * 1800
    await vault.upsert("s1", "user_note", long_ok, 300)
    with sqlite3.connect(db) as conn:
        stored = conn.execute(
            "SELECT value FROM facts WHERE session_id=? AND keyword=?",
            ("s1", "user_note"),
        ).fetchone()[0]
    assert len(stored) == 1800, "value under 2000 chars must be stored whole"

    # 3000 chars: truncated, never raises.
    huge = "word " * 600
    await vault.upsert("s1", "user_big", huge, 600)
    with sqlite3.connect(db) as conn:
        stored_big = conn.execute(
            "SELECT value FROM facts WHERE session_id=? AND keyword=?",
            ("s1", "user_big"),
        ).fetchone()[0]
    assert len(stored_big) <= 2003
    assert stored_big.startswith("word word")


@pytest.mark.asyncio
async def test_sqlite_backend_rejects_bad_input():
    backend = SQLiteBackend(":memory:")
    await backend.init_db()
    try:
        with pytest.raises(ValueError):
            await backend.upsert(LONG_ID, "user_name", "Alice", 1, 100, 2000)
        with pytest.raises(ValueError):
            await backend.upsert("", "user_name", "Alice", 1, 100, 2000)
        with pytest.raises(ValueError):
            await backend.upsert("s1", LONG_KEYWORD, "Alice", 1, 100, 2000)
        with pytest.raises(ValueError):
            await backend.retrieve_current(LONG_ID)
        with pytest.raises(ValueError):
            await backend.retrieve_current("")
        with pytest.raises(ValueError):
            await backend.touch("s1", [LONG_KEYWORD])
        with pytest.raises(ValueError):
            await backend.delete_session("")
        with pytest.raises(ValueError):
            await backend.get_fact_history("s1", LONG_KEYWORD)

        # Valid input still works.
        await backend.upsert("s1", "user_name", "Alice", 1, 100, 2000)
        assert await backend.retrieve_current("s1") == [("user_name", "Alice", 1)]
    finally:
        await backend.close()
