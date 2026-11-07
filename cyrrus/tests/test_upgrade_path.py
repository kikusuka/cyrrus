"""
Upgrade-path / migration tests (Item 5).

A database created by cyrrus==0.3.0b5 has the same `facts` table schema as
this branch but only two indexes (idx_session, idx_session_current) — it lacks
idx_session_keyword, which was added later to speed up touch()/upsert()
lookups. Opening such a DB with this branch must:

- Create idx_session_keyword on open (and preserve the existing indexes).
- Lose no data (row counts unchanged: total / active / superseded).
- Keep supersession history intact (all versions, chronological).
- Retrieve and rank correctly, including limit=None.

The legacy DB is reproduced here with raw sqlite3 (same DDL 0.3.0b5 emits) so
the test is self-contained — no PyPI install or second venv needed at run
time. Counts mirror a real 0.3.0b5 build: 50 sessions x 100 active facts, with
the first 4 keywords of each session superseded twice (3 versions each).
"""
import sqlite3
import time

import pytest

from cyrrus.sqlite_backend import SQLiteBackend


LEGACY_TABLE = """CREATE TABLE facts (
    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    keyword       TEXT NOT NULL,
    value         TEXT,
    tokens        INTEGER,
    last_accessed REAL,
    valid_at      TEXT NOT NULL,
    invalid_at    TEXT
)"""

N_SESSIONS = 50
PER_SESSION = 100
SUPERSEDE = 4
EXPECTED_TOTAL = N_SESSIONS * (SUPERSEDE * 3 + (PER_SESSION - SUPERSEDE))  # 5400
EXPECTED_ACTIVE = N_SESSIONS * PER_SESSION                                  # 5000
EXPECTED_SUPERSEDED = N_SESSIONS * SUPERSEDE * 2                            # 400


def _build_legacy_db(path):
    """Create a DB shaped exactly like cyrrus 0.3.0b5 output."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(LEGACY_TABLE)
        conn.execute("CREATE INDEX idx_session ON facts(session_id)")
        conn.execute(
            "CREATE INDEX idx_session_current ON facts(session_id, invalid_at) "
            "WHERE invalid_at IS NULL")
        now = 1700000000.0
        rows = []
        for s in range(N_SESSIONS):
            sid = "sess%03d" % s
            for k in range(SUPERSEDE):
                kw = "fact_%d" % k
                t1 = "2025-01-01T00:00:0%d" % k
                t2 = "2025-01-02T00:00:0%d" % k
                t3 = "2025-01-03T00:00:0%d" % k
                v1 = "ORIGINAL v1 %s %d %d" % (kw, s, k)
                v2 = "UPDATED v2 %s %d %d" % (kw, s, k)
                v3 = "CURRENT v3 %s %d %d" % (kw, s, k)
                rows.append((sid, kw, v1, len(v1.split()), now, t1, t2))
                rows.append((sid, kw, v2, len(v2.split()), now, t2, t3))
                rows.append((sid, kw, v3, len(v3.split()), now, t3, None))
            for k in range(SUPERSEDE, PER_SESSION):
                kw = "fact_%d" % k
                v = "python coffee %s %d %d value words here" % (kw, s, k)
                rows.append((sid, kw, v, len(v.split()), now,
                             "2025-01-01T00:00:00", None))
        conn.executemany(
            "INSERT INTO facts (session_id, keyword, value, tokens, "
            "last_accessed, valid_at, invalid_at) VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()


def _indexes(path):
    conn = sqlite3.connect(path)
    try:
        return sorted(
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='facts' AND name IS NOT NULL").fetchall())
    finally:
        conn.close()


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE invalid_at IS NULL").fetchone()[0]
        superseded = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE invalid_at IS NOT NULL").fetchone()[0]
        return total, active, superseded
    finally:
        conn.close()


def test_legacy_fixture_shape(tmp_path):
    """The reproduced legacy DB matches a real 0.3.0b5 build."""
    db = str(tmp_path / "legacy.db")
    _build_legacy_db(db)
    assert _counts(db) == (EXPECTED_TOTAL, EXPECTED_ACTIVE, EXPECTED_SUPERSEDED)
    idxs = _indexes(db)
    assert idxs == ["idx_session", "idx_session_current"]
    assert "idx_session_keyword" not in idxs


async def test_upgrade_creates_index_no_data_loss_history_intact(tmp_path):
    db = str(tmp_path / "legacy.db")
    _build_legacy_db(db)
    before = _counts(db)
    assert before == (EXPECTED_TOTAL, EXPECTED_ACTIVE, EXPECTED_SUPERSEDED)
    assert "idx_session_keyword" not in _indexes(db)

    be = SQLiteBackend(db)
    await be.init_db()

    # idx_session_keyword created on open; existing indexes preserved.
    idxs = _indexes(db)
    assert "idx_session_keyword" in idxs
    assert "idx_session" in idxs
    assert "idx_session_current" in idxs

    # No data loss.
    assert _counts(db) == before

    # Supersession history intact and chronological.
    hist = await be.get_fact_history("sess000", "fact_0")
    assert len(hist) == 3
    assert [h["value"].split()[1] for h in hist] == ["v1", "v2", "v3"]
    assert hist[0]["invalid_at"] is not None
    assert hist[1]["invalid_at"] is not None
    assert hist[2]["invalid_at"] is None  # current

    # Retrieval works on the migrated DB, including limit=None.
    rows = await be.retrieve_current("sess000", limit=None)
    assert len(rows) == PER_SESSION
    values = dict((kw, val) for kw, val, _t in rows)
    assert values["fact_0"].startswith("CURRENT v3")  # superseded versions excluded

    ranked, _dropped = await be.retrieve_ranked(
        "sess000", "python coffee value words here", limit=5)
    assert ranked
    assert all(isinstance(r[0], float) and r[0] > 0 for r in ranked)

    await be.close()


async def test_upgrade_is_idempotent(tmp_path):
    """Re-opening an already-migrated DB does not duplicate or drop anything."""
    db = str(tmp_path / "legacy.db")
    _build_legacy_db(db)
    be = SQLiteBackend(db)
    await be.init_db()
    await be.close()
    counts_after_first = _counts(db)

    be2 = SQLiteBackend(db)
    await be2.init_db()
    assert _counts(db) == counts_after_first
    idxs = _indexes(db)
    assert idxs.count("idx_session_keyword") == 1
    await be2.close()


async def test_upgrade_first_vs_later_timing(tmp_path):
    """Paste-able timing: first operation pays the one-time index build."""
    db = str(tmp_path / "timing.db")
    _build_legacy_db(db)
    be = SQLiteBackend(db)

    t = time.perf_counter(); await be.init_db(); init_ms = (time.perf_counter() - t) * 1000

    t = time.perf_counter(); await be.retrieve_ranked("sess000", "python coffee", limit=5); r1 = (time.perf_counter() - t) * 1000
    t = time.perf_counter(); await be.retrieve_ranked("sess000", "guitar jazz", limit=5); r2 = (time.perf_counter() - t) * 1000

    t = time.perf_counter(); await be.upsert("sess000", "fact_100", "brand new fact", 3, None, 4096); u1 = (time.perf_counter() - t) * 1000
    t = time.perf_counter(); await be.upsert("sess000", "fact_101", "another new fact", 3, None, 4096); u2 = (time.perf_counter() - t) * 1000

    t = time.perf_counter(); await be.touch("sess000", ["fact_0"]); t1 = (time.perf_counter() - t) * 1000
    t = time.perf_counter(); await be.touch("sess000", ["fact_1"]); t2 = (time.perf_counter() - t) * 1000

    print("\n[upgrade-timing] init_db(add idx_session_keyword on 5400 rows)=%.2fms" % init_ms)
    print("[upgrade-timing] retrieve first=%.2fms later=%.2fms" % (r1, r2))
    print("[upgrade-timing] upsert   first=%.2fms later=%.2fms" % (u1, u2))
    print("[upgrade-timing] touch    first=%.2fms later=%.2fms" % (t1, t2))

    await be.close()
