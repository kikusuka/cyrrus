"""
Item 1 (phase 1c): stale-index race regression tests (P0).

PRAGMA data_version on a connection changes ONLY when another connection
commits; a connection's own commits do not bump it (verified: own commit
2->2, other-connection commit 2->3). The phase-1b touch() refreshed the
cached index's data_version stamp after its own commit. Because the external
write had already bumped this connection's data_version, touch() stamped the
*new* version onto the *old* index -- absorbing the concurrent change without
a rebuild. A supersede made by a second connection/process was therefore
never seen: retrieve kept returning the stale value forever.

The fix: touch() must not advance the stamp. The stamp only ever advances at
a rebuild (in retrieve_ranked), so an external commit always forces a rebuild
on the next retrieve.

All three tests below fail on the pre-fix code and pass after the fix.
"""
import asyncio
import datetime
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.sqlite_backend import SQLiteBackend


def _content(ranked):
    """Tie-order-insensitive content of a ranked result.

    Deterministic tie ORDER is item 2's concern; here we assert the index
    returns the same facts/values/scores as a fresh DB ranking (sorted by
    keyword), which is exactly what the stale-index bug violates.
    """
    return sorted((kw, val, round(score, 9)) for score, kw, val, _tok in ranked)


def _external_supersede(db, session, keyword, new_value, tokens=3):
    """Supersede (session, keyword) -> new_value from a SEPARATE connection."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        now = datetime.datetime.now().isoformat()
        conn.execute(
            "UPDATE facts SET invalid_at=? WHERE session_id=? AND keyword=? "
            "AND invalid_at IS NULL", (now, session, keyword))
        conn.execute(
            "INSERT INTO facts (session_id,keyword,value,tokens,last_accessed,"
            "valid_at) VALUES (?,?,?,?,?,?)",
            (session, keyword, new_value, tokens, time.time(), now))
        conn.commit()
    finally:
        conn.close()


async def test_external_supersede_visible_after_touch(tmp_path):
    """Two-connection repro: external supersede + touch must not go stale."""
    db = str(tmp_path / "race.db")
    be = SQLiteBackend(db)
    try:
        await be.init_db()
        await be.upsert("s", "user_location", "zeta zeta Lisbon", 3, None, 4096)
        ranked, _ = await be.retrieve_ranked("s", "zeta zeta", limit=10)
        assert [v for _s, _k, v, _t in ranked] == ["zeta zeta Lisbon"]

        # A second connection supersedes Lisbon -> Porto.
        _external_supersede(db, "s", "user_location", "zeta zeta Porto")
        # touch() on the FIRST (backend) connection: pre-fix this absorbs the
        # external data_version bump onto the stale index.
        await be.touch("s", ["user_location"])

        ranked, _ = await be.retrieve_ranked("s", "zeta zeta", limit=10)
        values = [v for _s, _k, v, _t in ranked]
        assert values == ["zeta zeta Porto"], "stale index returned %r" % (values,)
    finally:
        await be.close()


_PROC_WRITER = (
    "import sqlite3, datetime, time, sys\n"
    "db, sess, kw, val = sys.argv[1:5]\n"
    "c = sqlite3.connect(db)\n"
    "c.execute('PRAGMA journal_mode=WAL')\n"
    "c.execute('PRAGMA busy_timeout=5000')\n"
    "now = datetime.datetime.now().isoformat()\n"
    "c.execute('UPDATE facts SET invalid_at=? WHERE session_id=? AND keyword=? "
    "AND invalid_at IS NULL', (now, sess, kw))\n"
    "c.execute('INSERT INTO facts (session_id,keyword,value,tokens,last_accessed,"
    "valid_at) VALUES (?,?,?,?,?,?)', (sess, kw, val, 3, time.time(), now))\n"
    "c.commit(); c.close()\n"
)


def test_separate_process_writer_visible(tmp_path):
    """A supersede committed by a separate PROCESS must be seen after touch."""
    db = str(tmp_path / "proc.db")

    async def run():
        be = SQLiteBackend(db)
        try:
            await be.init_db()
            await be.upsert("s", "user_city", "zeta zeta Madrid", 3, None, 4096)
            ranked, _ = await be.retrieve_ranked("s", "zeta zeta", limit=10)
            assert [v for _s, _k, v, _t in ranked] == ["zeta zeta Madrid"]

            await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-c", _PROC_WRITER, db, "s", "user_city",
                 "zeta zeta Toledo"],
                check=True,
            )
            await be.touch("s", ["user_city"])
            ranked, _ = await be.retrieve_ranked("s", "zeta zeta", limit=10)
            values = [v for _s, _k, v, _t in ranked]
            assert values == ["zeta zeta Toledo"], (
                "stale index returned %r" % (values,))
        finally:
            await be.close()

    asyncio.run(run())


async def test_concurrent_stress_index_matches_db(tmp_path):
    """8 external-writer threads + 50 asyncio tasks of mixed
    upsert/supersede/retrieve/touch, then a quiescent invariant check that
    also replays the exact P0 trigger (external write -> touch -> retrieve)
    for every session.
    """
    db = str(tmp_path / "stress.db")
    be = SQLiteBackend(db)
    n_tasks, n_threads = 50, 8
    task_sessions = ["tsk%d" % i for i in range(n_tasks)]
    ext_sessions = ["ext%d" % i for i in range(n_threads)]
    stop = threading.Event()
    errors = []

    try:
        await be.init_db()
        # Test-only: avoid SQLITE_BUSY under heavy multi-connection contention.
        be._conn.execute("PRAGMA busy_timeout=5000")
        for s in task_sessions + ext_sessions:
            await be.upsert(s, "pk", "zeta zeta seed", 3, None, 4096)
            for j in range(6):
                await be.upsert(s, "filler%d" % j,
                                "zeta filler %d %s" % (j, s), 3, None, 4096)

        def writer(tid):
            conn = sqlite3.connect(db)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            s = ext_sessions[tid]
            i = 0
            try:
                while not stop.is_set() and i < 40:
                    now = datetime.datetime.now().isoformat()
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute(
                            "UPDATE facts SET invalid_at=? WHERE session_id=? "
                            "AND keyword='pk' AND invalid_at IS NULL", (now, s))
                        conn.execute(
                            "INSERT INTO facts (session_id,keyword,value,tokens,"
                            "last_accessed,valid_at) VALUES (?,?,?,?,?,?)",
                            (s, "pk", "zeta zeta ext%d_%d" % (tid, i), 3,
                             time.time(), now))
                        conn.commit()
                    except sqlite3.OperationalError:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    i += 1
            except Exception as e:  # pragma: no cover
                errors.append(("writer", repr(e)))
            finally:
                conn.close()

        async def task(tid):
            s = task_sessions[tid]
            es = ext_sessions[tid % n_threads]
            try:
                for i in range(12):
                    await be.upsert(s, "pk", "zeta zeta t%d_%d" % (tid, i),
                                    3, None, 4096)
                    await be.retrieve_ranked(s, "zeta zeta", limit=100)
                    await be.touch(s, ["pk"])
                    ranked, _ = await be.retrieve_ranked(s, "zeta zeta", limit=100)
                    rows = await be.retrieve_current(s, limit=None)
                    fresh = bm25_rank_facts(rows, "zeta zeta", limit=100)
                    if _content(ranked) != _content(fresh):
                        errors.append(("task-invariant", tid, i,
                                       _content(ranked), _content(fresh)))
                        return
                    # Exercise the P0 path concurrently (external writers own
                    # es); no concurrent assertion here because it is racy.
                    await be.retrieve_ranked(es, "zeta zeta", limit=100)
                    await be.touch(es, ["pk"])
            except Exception as e:  # pragma: no cover
                errors.append(("task", repr(e)))

        threads = [threading.Thread(target=writer, args=(t,), daemon=True)
                   for t in range(n_threads)]
        for t in threads:
            t.start()
        await asyncio.gather(*[task(i) for i in range(n_tasks)])
        stop.set()
        for t in threads:
            t.join(timeout=30)

        assert not errors, "errors during stress: %r" % (errors[:5],)

        # Quiescent invariant + explicit P0 trigger for every session.
        for s in task_sessions + ext_sessions:
            await be.upsert(s, "pk", "zeta zeta OLD", 3, None, 4096)
            await be.retrieve_ranked(s, "zeta zeta", limit=1000)  # cache index
            _external_supersede(db, s, "pk", "zeta zeta NEW")      # other conn
            await be.touch(s, ["pk"])                              # pre-fix absorbs
            ranked, _ = await be.retrieve_ranked(s, "zeta zeta", limit=1000)
            rows = await be.retrieve_current(s, limit=None)
            fresh = bm25_rank_facts(rows, "zeta zeta", limit=1000)
            assert _content(ranked) == _content(fresh), (
                "session %s stale: index=%r fresh=%r"
                % (s, _content(ranked), _content(fresh)))
            assert any(val == "zeta zeta NEW" for _sc, _kw, val, _t in ranked), (
                "session %s did not surface NEW value: %r" % (s, ranked))
    finally:
        stop.set()
        await be.close()
