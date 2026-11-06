"""
Item 4 (phase v6-segv): genuine DB file recreation UNDER LOAD.

Item 2 made replacement detection inode-based; item 3 made _reset_connection
safe against in-flight use (RLock + re-check under the lock). This test
exercises both together and is the failing-test-first driver for item 3's
locking: while 8 threads hammer the backend with reads, the live DB file is
genuinely replaced (os.replace of a second, fully populated file onto the live
path, as in test_file_identity (b)) several times.

On Linux the path can be replaced while the backend holds it open. A reading
thread then detects the inode change and calls _reset_connection, which closes
the SHARED connection. Without item 3's lock that close races with the other
threads' in-flight statements (use-after-free -> SIGSEGV). With the lock, the
close serializes against readers.

Assertions: no crash, no "closed database"/"malformed" errors surface, and once
the swap settles every session reads the post-swap value.

Windows cannot replace a file with an open handle (PermissionError); there the
swap is skipped and only the crash-free concurrent-read path is exercised.
"""
import asyncio
import os
import sqlite3
import threading
import time

import pytest

from cyrrus.sqlite_backend import SQLiteBackend


_BEFORE = "zeta zeta BEFORE"
_AFTER = "zeta zeta AFTER"
_VALID = (_BEFORE, _AFTER)


def _build_standalone_db(path, value, n_sessions=8):
    """Create a complete, self-contained DB file (DELETE journal, no WAL
    residue) holding one 'pk' fact per session, all set to `value`."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute(
            "CREATE TABLE facts (rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, keyword TEXT NOT NULL, value TEXT, "
            "tokens INTEGER, last_accessed REAL, valid_at TEXT NOT NULL, "
            "invalid_at TEXT)")
        conn.execute("CREATE INDEX idx_session ON facts(session_id)")
        now = time.time()
        for s in range(n_sessions):
            conn.execute(
                "INSERT INTO facts (session_id, keyword, value, tokens, "
                "last_accessed, valid_at) VALUES (?,?,?,?,?,?)",
                ("s%d" % s, "pk", value, len(value.split()), now,
                 "2025-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def test_genuine_recreation_under_load(tmp_path):
    db = str(tmp_path / "live.db")
    _build_standalone_db(db, _BEFORE)

    be = SQLiteBackend(db)
    stop = threading.Event()
    errors = []
    n_threads = 8

    def worker(tid):
        sid = "s%d" % tid

        async def loop():
            while not stop.is_set():
                try:
                    rows = await be.retrieve_current(sid, limit=None)
                    for _kw, val, _tok in rows:
                        if val not in _VALID:
                            errors.append(("bad-value", tid, val))
                            return
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    # A transient reinit is fine; a closed/half-torn-down
                    # connection escaping to a caller is the bug we guard.
                    if "closed" in msg or "malformed" in msg:
                        errors.append(("closed-db", tid, str(e)))
                        return
                except Exception as e:  # pragma: no cover - defensive
                    errors.append(("worker", tid, repr(e)))
                    return

        try:
            asyncio.run(loop())
        except Exception as e:  # pragma: no cover - defensive
            errors.append(("worker-outer", tid, repr(e)))

    try:
        threads = [threading.Thread(target=worker, args=(t,), daemon=True)
                   for t in range(n_threads)]
        for t in threads:
            t.start()

        # Let the read load spin up, then genuinely replace the DB file
        # underneath the live backend several times.
        time.sleep(0.2)
        replace_ok = True
        rounds = 5
        for r in range(rounds):
            swap = str(tmp_path / ("swap%d.db" % r))
            _build_standalone_db(swap, _AFTER)
            try:
                os.replace(swap, db)
            except PermissionError:
                # Windows: cannot replace a file with an open handle.
                replace_ok = False
                _unlink_quiet(swap)
                break
            except OSError as e:  # pragma: no cover - defensive
                errors.append(("replace", repr(e)))
                replace_ok = False
                break
            # Drop the previous inode's stale WAL side-files so the freshly
            # reopened DB does not see a mismatched journal.
            _unlink_quiet(db + "-wal")
            _unlink_quiet(db + "-shm")
            time.sleep(0.15)

        # Give readers time to observe the swap, reset, and reinitialize.
        time.sleep(0.5)
        stop.set()
        for t in threads:
            t.join(timeout=30)

        assert not errors, "errors under load: %r" % (errors[:5],)

        if not replace_ok:
            pytest.skip("OS forbids replacing an open DB file "
                        "(concurrent-read path only)")

        # Quiescent correctness: every session reads the post-swap value.
        async def final():
            await be.init_db()
            out = {}
            for s in range(n_threads):
                rows = await be.retrieve_current("s%d" % s, limit=None)
                out["s%d" % s] = [v for _k, v, _t in rows]
            return out

        result = asyncio.run(final())
        for sid, vals in result.items():
            assert vals == [_AFTER], "session %s after swap: %r" % (sid, vals)
    finally:
        stop.set()
        try:
            asyncio.run(be.close())
        except Exception:
            pass
