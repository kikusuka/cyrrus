"""
Tests for LRU eviction of the cached per-session BM25 indexes (Item 3).

The SQLiteBackend caches one SessionFactIndex per session in self._indexes.
Without a cap, a long-lived process that touches many sessions grows the
cache without bound. These tests assert:

- The cache is bounded by session count and by total indexed docs.
- Defaults are safe (64 sessions / 200k docs) and env/ctor configurable.
- Evicted sessions rebuild transparently and rank identically to a fresh
  bm25_rank_facts over the DB rows.
- Process RSS stays bounded across 500 sessions x 200 facts.
"""
import sqlite3
import sys
import time

import pytest

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.sqlite_backend import SQLiteBackend


def _rss_bytes() -> int:
    """Best-effort resident set size in bytes (Windows working set / Unix RSS)."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            k32 = ctypes.windll.kernel32
            fn = k32.K32GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            handle = k32.GetCurrentProcess()
            if fn(handle, ctypes.byref(pmc), pmc.cb):
                return int(pmc.WorkingSetSize)
    except Exception:
        pass
    try:
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes, Linux reports kilobytes.
        return int(ru) if sys.platform == "darwin" else int(ru) * 1024
    except Exception:
        return 0


def _bulk_seed(db: str, n_sessions: int, n_facts: int) -> None:
    """Fast direct seed via a raw connection (bypasses per-row upsert)."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        now = time.time()
        valid = "2025-01-01T00:00:00"
        rows = []
        for s in range(n_sessions):
            sid = "sess%04d" % s
            for f in range(n_facts):
                kw = "fact_%d" % f
                val = "python coffee guitar jazz %d %d value words here" % (s, f)
                rows.append((sid, kw, val, len(val.split()), now, valid))
        conn.executemany(
            "INSERT INTO facts (session_id, keyword, value, tokens, "
            "last_accessed, valid_at) VALUES (?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


async def test_index_cache_bounded_over_many_sessions(tmp_path):
    db = str(tmp_path / "evict.db")
    be = SQLiteBackend(db)
    await be.init_db()
    _bulk_seed(db, 500, 200)

    rss_before = _rss_bytes()
    # Warm a bounded window, then sweep across all 500 sessions so the LRU
    # must evict to stay under the default caps.
    for s in range(64):
        await be.retrieve_ranked("sess%04d" % s, "python coffee", limit=3)
    for s in range(500):
        await be.retrieve_ranked("sess%04d" % s, "guitar jazz", limit=3)
    rss_after = _rss_bytes()

    assert len(be._indexes) <= 64, "cached sessions unbounded: %d" % len(be._indexes)
    assert be._index_total_docs <= 200000, "cached docs unbounded: %d" % be._index_total_docs
    assert be._index_total_docs <= 64 * 200, "docs exceed session cap: %d" % be._index_total_docs

    growth_mb = (rss_after - rss_before) / (1024.0 * 1024.0)
    print(
        "\n[eviction] RSS before=%.1fMB after=%.1fMB growth=%.1fMB "
        "cached_sessions=%d cached_docs=%d"
        % (
            rss_before / (1024.0 * 1024.0),
            rss_after / (1024.0 * 1024.0),
            growth_mb,
            len(be._indexes),
            be._index_total_docs,
        )
    )
    assert growth_mb < 100.0, "RSS grew %.1fMB across the sweep" % growth_mb

    # An evicted session must rebuild and rank identically to a fresh ranking.
    rows = await be.retrieve_current("sess0000", limit=None)
    ranked, _dropped = await be.retrieve_ranked("sess0000", "python coffee", limit=5)
    expected = bm25_rank_facts(rows, "python coffee", limit=5, score_threshold=0.0)
    assert ranked == expected

    await be.close()


async def test_index_cache_bounded_by_doc_cap(tmp_path):
    db = str(tmp_path / "doccap.db")
    be = SQLiteBackend(db, max_cached_docs=1000)
    await be.init_db()
    _bulk_seed(db, 20, 200)
    for s in range(20):
        await be.retrieve_ranked("sess%04d" % s, "python", limit=3)
    assert be._index_total_docs <= 1000, "doc cap exceeded: %d" % be._index_total_docs
    assert len(be._indexes) <= 5, "session count exceeds doc cap: %d" % len(be._indexes)
    await be.close()


def test_default_caps(tmp_path):
    be = SQLiteBackend(str(tmp_path / "d.db"))
    assert be._max_cached_sessions == 64
    assert be._max_cached_docs == 200000


def test_caps_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CYRRUS_INDEX_MAX_SESSIONS", "7")
    monkeypatch.setenv("CYRRUS_INDEX_MAX_DOCS", "1234")
    be = SQLiteBackend(str(tmp_path / "e.db"))
    assert be._max_cached_sessions == 7
    assert be._max_cached_docs == 1234


async def test_evicted_session_rebuilds_identically(tmp_path):
    db = str(tmp_path / "lru.db")
    be = SQLiteBackend(db, max_cached_sessions=2)
    await be.init_db()
    _bulk_seed(db, 3, 50)
    for s in range(3):
        await be.retrieve_ranked("sess%04d" % s, "python coffee", limit=3)
    assert len(be._indexes) <= 2
    assert "sess0000" not in be._indexes, "LRU should have evicted the oldest session"
    rows = await be.retrieve_current("sess0000", limit=None)
    ranked, _dropped = await be.retrieve_ranked("sess0000", "python coffee", limit=5)
    assert ranked == bm25_rank_facts(rows, "python coffee", limit=5, score_threshold=0.0)
    await be.close()
