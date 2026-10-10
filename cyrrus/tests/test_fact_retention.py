"""
Step 2: optional per-session fact cap (max_facts_per_session, default None = unlimited).

When a cap is set and exceeded, the oldest superseded facts are deleted first,
then the oldest active facts.
"""
import sqlite3

import pytest

from cyrrus import MemoryVault


@pytest.mark.asyncio
async def test_superseded_evicted_before_active(tmp_path):
    db = str(tmp_path / "retention.db")
    vault = MemoryVault(db_path=db, max_facts_per_session=3)

    await vault.upsert("s1", "user_a", "A1", 1)
    await vault.upsert("s1", "user_b", "B1", 1)
    await vault.upsert("s1", "user_c", "C1", 1)
    await vault.upsert("s1", "user_a", "A2", 1)  # supersedes user_a=A1

    with sqlite3.connect(db) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE session_id='s1'"
        ).fetchone()[0]
        superseded = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE session_id='s1' AND invalid_at IS NOT NULL"
        ).fetchone()[0]
        current = dict(conn.execute(
            "SELECT keyword, value FROM facts WHERE session_id='s1' AND invalid_at IS NULL"
        ).fetchall())

    assert total == 3, f"cap must hold at 3 rows total, got {total}"
    assert superseded == 0, "the superseded row must be evicted before any active fact"
    assert current == {"user_a": "A2", "user_b": "B1", "user_c": "C1"}


@pytest.mark.asyncio
async def test_oldest_active_evicted_when_no_superseded(tmp_path):
    db = str(tmp_path / "retention_active.db")
    vault = MemoryVault(db_path=db, max_facts_per_session=2)

    await vault.upsert("s1", "key_0", "val_0", 1)
    await vault.upsert("s1", "key_1", "val_1", 1)
    await vault.upsert("s1", "key_2", "val_2", 1)

    with sqlite3.connect(db) as conn:
        current = dict(conn.execute(
            "SELECT keyword, value FROM facts WHERE session_id='s1' AND invalid_at IS NULL"
        ).fetchall())

    assert current == {"key_1": "val_1", "key_2": "val_2"}


@pytest.mark.asyncio
async def test_default_is_unlimited(tmp_path):
    db = str(tmp_path / "retention_default.db")
    vault = MemoryVault(db_path=db)
    assert vault.max_facts_per_session is None, "default must be None (unlimited)"

    for i in range(25):
        await vault.upsert("s1", f"key_{i}", f"val_{i}", 1)

    with sqlite3.connect(db) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE session_id='s1'"
        ).fetchone()[0]
    assert total == 25
