"""
Item 2 (phase v6-segv): DB file identity via (st_dev, st_ino), not ctime.

On Linux/macOS ``os.path.getctime`` returns the inode CHANGE time, which a
routine WAL checkpoint bumps. The old code misread that as "file recreated"
and closed the shared connection out from under live worker threads, causing a
use-after-free segfault (tests/test_stale_index.py crashed 20/20 in Docker).

Identity must therefore be based on the file's (device, inode) pair:

  (a) writing + ``PRAGMA wal_checkpoint(TRUNCATE)`` on the SAME file rewrites
      the main DB (bumping ctime/mtime) but keeps the SAME inode -> the file
      must NOT be reported as recreated;
  (b) ``os.replace`` of a DIFFERENT, coexisting file onto the path changes the
      inode -> the file MUST be reported as recreated. (b) uses two coexisting
      files + os.replace so the inode really differs; delete-then-recreate is
      deliberately avoided because Linux reuses freed inode numbers.

Both tests are OS-independent. If the filesystem reports ``st_ino == 0`` (some
network/FAT mounts) detection is skipped rather than guessed; the tests no-op
in that case, and (c) exercises the skip path directly via a faked stat.
"""
import os
import sqlite3

import pytest

from cyrrus.sqlite_backend import SQLiteBackend


def _close_backend(be):
    """Close a backend's raw connection without touching asyncio."""
    conn = getattr(be, "_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _usable_inode(path):
    """True if the filesystem reports a real (non-zero) inode for path."""
    try:
        return os.stat(path).st_ino != 0
    except OSError:
        return False


def _facts_ddl(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS facts (rowid INTEGER PRIMARY KEY "
        "AUTOINCREMENT, session_id TEXT NOT NULL, keyword TEXT NOT NULL, "
        "value TEXT, tokens INTEGER, last_accessed REAL, valid_at TEXT NOT "
        "NULL, invalid_at TEXT)")


def test_checkpoint_same_file_is_not_recreated(tmp_path):
    """(a) A second-connection write + WAL checkpoint(TRUNCATE) rewrites the
    main DB file in place. That bumps ctime/mtime but keeps the SAME inode, so
    inode-based identity detection must NOT report the file as recreated.

    On the pre-fix ctime code this returns True on Linux (checkpoint bumps
    st_ctime) and the assertion fails.
    """
    db = str(tmp_path / "a.db")
    be = SQLiteBackend(db)
    try:
        be._get_connection()  # records the initial file identity
        if not _usable_inode(db):
            pytest.skip("filesystem reports st_ino == 0; identity detection skipped")

        # External connection writes rows then truncates the WAL, forcing a
        # checkpoint that rewrites the main DB file (same inode).
        conn2 = sqlite3.connect(db)
        try:
            _facts_ddl(conn2)
            for i in range(50):
                conn2.execute(
                    "INSERT INTO facts (session_id, keyword, value, tokens, "
                    "last_accessed, valid_at) VALUES ('s',?,?,1,1.0,"
                    "'2025-01-01T00:00:00')", ("k%d" % i, "v%d" % i))
            conn2.commit()
            conn2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn2.close()

        # Inode unchanged -> not recreated. The backend connection must also
        # survive (a false positive would have reset/closed it).
        conn_before = be._conn
        assert be._check_file_recreated() is False, (
            "checkpoint falsely reported the DB file as recreated "
            "(ctime-based detection); identity must be inode-based")
        assert be._conn is conn_before, (
            "connection was reset by a false recreation detection")
    finally:
        _close_backend(be)


def test_os_replace_different_file_is_recreated(tmp_path):
    """(b) os.replace of a DIFFERENT coexisting file onto the DB path changes
    the inode, so identity detection MUST report the file as recreated.

    Two files are created first (A recorded by the backend, B separate) so
    their inodes differ; delete-then-recreate is NOT used because Linux reuses
    freed inode numbers and could hand back the same one.

    The backend's raw OS file handle on A is released (closed directly, NOT via
    _reset_connection, so the recorded identity survives) before the swap:
    Windows refuses os.replace onto a path with an open handle, while the
    recorded (st_dev, st_ino) identity is what _check_file_recreated compares
    against. This keeps the test OS-independent.
    """
    db = str(tmp_path / "a.db")
    db_b = str(tmp_path / "b.db")
    be = SQLiteBackend(db)
    try:
        be._get_connection()  # records identity of file A

        # Build B as a separate, real database file.
        conn_b = sqlite3.connect(db_b)
        try:
            _facts_ddl(conn_b)
            conn_b.execute(
                "INSERT INTO facts (session_id, keyword, value, tokens, "
                "last_accessed, valid_at) VALUES ('s','k','fresh',1,1.0,"
                "'2025-01-01T00:00:00')")
            conn_b.commit()
        finally:
            conn_b.close()

        ino_a = os.stat(db).st_ino
        ino_b = os.stat(db_b).st_ino
        if ino_a == 0 or ino_b == 0:
            pytest.skip("filesystem reports st_ino == 0; identity detection skipped")
        assert ino_a != ino_b, "test setup: A and B must be distinct inodes"

        # Release A's OS handle (keeping the recorded identity) so the swap is
        # permitted on Windows too.
        if be._conn is not None:
            be._conn.close()
            be._conn = None

        # Swap B onto A's path. The path now resolves to B's inode.
        os.replace(db_b, db)

        assert be._check_file_recreated() is True, (
            "a genuine file replacement (inode change) was not detected")
        # Detection reset the (already-closed) connection so the next op
        # reinitializes cleanly.
        assert be._conn is None
    finally:
        _close_backend(be)


def test_inode_zero_skips_detection(tmp_path, monkeypatch):
    """(c) When the filesystem cannot report a usable inode (st_ino == 0), the
    detector must skip rather than guess: it returns False and leaves the live
    connection untouched even though the path still resolves to a file.
    """
    db = str(tmp_path / "z.db")
    be = SQLiteBackend(db)
    try:
        be._get_connection()
        conn_before = be._conn
        assert conn_before is not None

        real_stat = os.stat

        class _FakeStat:
            # Present but unusable inode; a fixed ctime that differs from the
            # recorded one so the pre-fix ctime code would (wrongly) fire.
            st_ino = 0
            st_dev = 0
            st_ctime = 12345.0
            st_mtime = 12345.0
            st_size = 0

        def fake_stat(path, *a, **k):
            if str(path) == db:
                return _FakeStat()
            return real_stat(path, *a, **k)

        monkeypatch.setattr(os, "stat", fake_stat)
        assert be._check_file_recreated() is False, (
            "detection guessed on an unusable inode instead of skipping")
        assert be._conn is conn_before, (
            "connection was reset despite unusable inode")
    finally:
        _close_backend(be)
