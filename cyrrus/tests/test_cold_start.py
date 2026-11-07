"""
Tests for the optional cold-start warm-up (Item 4).

The gateway may pre-build retrieval indexes for the most-recently-used
sessions on a background daemon thread so the first retrieve for those
sessions hits a warm index instead of building cold. Warm-up must:

- Select sessions by recency (latest last_accessed) and respect the limit.
- Build indexes identical to the on-demand path (rankings unchanged).
- Never raise when the schema is missing or the limit is zero.
- Be started by the gateway only when memory.warmup_sessions > 0, on a
  daemon thread that does not block construction.
"""
import sqlite3

import pytest

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.sqlite_backend import SQLiteBackend


def _seed_session(conn, sid, n, last_accessed):
    for f in range(n):
        v = "python coffee guitar jazz %d value words here" % f
        conn.execute(
            "INSERT INTO facts (session_id, keyword, value, tokens, "
            "last_accessed, valid_at) VALUES (?,?,?,?,?,?)",
            (sid, "fact_%d" % f, v, len(v.split()), last_accessed,
             "2025-01-01T00:00:00"),
        )


def _gateway_config(db, warmup):
    return {
        "gateway": {
            "host": "127.0.0.1", "port": 0, "mode": "inject",
            "session": "default", "fail_open": True, "force_model": None,
            "api_key_env": None, "upstream_timeout": 60.0,
        },
        "provider": {"base_url": None, "model": None, "api_key_env": None,
                     "service": None},
        "memory": {"db_path": db, "warmup_sessions": warmup,
                   "max_facts_per_session": 50},
        "context": {"max_context_tokens": 4000,
                    "slides_path": "definitely-missing-slides.json"},
    }


async def test_warm_recent_sync_builds_mru_indexes(tmp_path):
    db = str(tmp_path / "warm.db")
    be = SQLiteBackend(db)
    await be.init_db()
    with be._thread_lock:
        conn = be._get_connection()
        _seed_session(conn, "old", 30, 1000.0)
        _seed_session(conn, "mid", 30, 2000.0)
        _seed_session(conn, "new", 30, 3000.0)
        conn.commit()

    warmed = be.warm_recent_sync(2)
    assert warmed == 2
    # 'old' is the least-recently-used and must not be warmed.
    assert set(be._indexes.keys()) == {"new", "mid"}
    assert be._index_total_docs == 60

    # A warmed index ranks identically to a fresh ranking (cache hit path).
    rows = await be.retrieve_current("new", limit=None)
    ranked, _dropped = await be.retrieve_ranked("new", "python coffee", limit=5)
    assert ranked == bm25_rank_facts(rows, "python coffee", limit=5,
                                     score_threshold=0.0)
    await be.close()


def test_warm_recent_sync_missing_schema_is_noop(tmp_path):
    db = str(tmp_path / "empty.db")
    sqlite3.connect(db).close()  # file exists, no 'facts' table
    be = SQLiteBackend(db)
    assert be.warm_recent_sync(5) == 0
    assert be._indexes == {}


def test_warm_recent_sync_zero_limit(tmp_path):
    be = SQLiteBackend(str(tmp_path / "z.db"))
    assert be.warm_recent_sync(0) == 0


def test_gateway_starts_warmup_thread_when_configured(tmp_path):
    from cyrrus.gateway import Gateway

    db = str(tmp_path / "gw.db")
    seed = sqlite3.connect(db)
    try:
        seed.execute("PRAGMA journal_mode=WAL")
        seed.execute(
            "CREATE TABLE facts (rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, keyword TEXT NOT NULL, value TEXT, "
            "tokens INTEGER, last_accessed REAL, valid_at TEXT NOT NULL, "
            "invalid_at TEXT)")
        _seed_session(seed, "s1", 20, 5000.0)
        seed.commit()
    finally:
        seed.close()

    gw = Gateway(_gateway_config(db, 4))
    loop_thread = gw._loop_thread
    assert loop_thread is not None and loop_thread.is_alive(), (
        "expected a live cyrrus-event-loop thread before close()")
    try:
        assert gw.warmup_thread is not None
        assert gw.warmup_thread.daemon is True
        gw.warmup_thread.join(timeout=10)
        assert not gw.warmup_thread.is_alive()
        backend = gw.projector.memory._backend
        assert "s1" in backend._indexes
    finally:
        gw.close()
    # The leak this guards: without close() the daemon loop thread survives the
    # test. close() must stop and join it.
    assert not loop_thread.is_alive(), (
        "cyrrus-event-loop thread survived Gateway.close()")


def test_gateway_no_warmup_by_default(tmp_path):
    from cyrrus.gateway import Gateway

    gw = Gateway(_gateway_config(str(tmp_path / "off.db"), 0))
    loop_thread = gw._loop_thread
    try:
        assert gw.warmup_thread is None
    finally:
        gw.close()
    assert loop_thread is not None
    assert not loop_thread.is_alive(), (
        "cyrrus-event-loop thread survived Gateway.close()")
