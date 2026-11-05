from __future__ import annotations
"""
SQLite backend implementation for MemoryVault.

This is the default zero-dependency backend, wrapping the existing
SQLite logic that was previously hardcoded in MemoryVault.
"""
import sqlite3
import time
import logging
import os
import sys
from collections import OrderedDict
from typing import List, Dict, Any, Optional
import asyncio
import threading
from .backend import MemoryBackend, validate_session_id, validate_keyword
from .bm25_index import SessionFactIndex


log = logging.getLogger("cyrrus.sqlite_backend")

# Safe defaults for the per-session index cache. A long-lived process that
# touches many sessions would otherwise grow self._indexes without bound.
DEFAULT_MAX_CACHED_SESSIONS = 64
DEFAULT_MAX_CACHED_DOCS = 200000


def _resolve_cap(explicit: Optional[int], env_var: str, default: int) -> Optional[int]:
    """Resolve a cache cap: explicit ctor arg > env var > built-in default.

    A non-positive resolved value means "unbounded" (returns None).
    """
    if explicit is not None:
        value = explicit
    else:
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            value = default
        else:
            try:
                value = int(raw)
            except ValueError:
                log.warning("Ignoring invalid %s=%r; using default %d.", env_var, raw, default)
                value = default
    return value if value and value > 0 else None


def default_db_path() -> str:
    r"""Resolve the default memory database path.

    Order: CYRRUS_DB_PATH environment variable if set; else a per-user data
    folder (Windows: %LOCALAPPDATA%\cyrrus\memory.db; macOS/Linux:
    $XDG_DATA_HOME or ~/.local/share/cyrrus/memory.db). The containing folder
    is created if missing.
    """
    env_path = os.environ.get("CYRRUS_DB_PATH")
    if env_path:
        result = env_path
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "cyrrus")
        os.makedirs(folder, exist_ok=True)
        result = os.path.join(folder, "memory.db")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        folder = os.path.join(base, "cyrrus")
        os.makedirs(folder, exist_ok=True)
        result = os.path.join(folder, "memory.db")

    log.info("Using default memory database at %s", os.path.abspath(result))
    return result


# Global registry of backend instances per DB path
# This ensures a single persistent connection per DB file
_backend_registry: dict[str, "SQLiteBackend"] = {}
_registry_lock = threading.Lock()


def get_backend(
    db_path: str,
    max_cached_sessions: Optional[int] = None,
    max_cached_docs: Optional[int] = None,
) -> "SQLiteBackend":
    """Get or create a backend instance for the given DB path (singleton per path).

    The cache-cap arguments only take effect when a new backend is created;
    an existing singleton is returned unchanged.
    """
    with _registry_lock:
        if db_path not in _backend_registry:
            _backend_registry[db_path] = SQLiteBackend(
                db_path,
                max_cached_sessions=max_cached_sessions,
                max_cached_docs=max_cached_docs,
            )
        return _backend_registry[db_path]


def close_backend(db_path: str) -> None:
    """Close and remove a backend from the registry."""
    with _registry_lock:
        if db_path in _backend_registry:
            backend = _backend_registry.pop(db_path)
            # Close synchronously
            if backend._conn:
                try:
                    backend._conn.close()
                except:
                    pass
                backend._conn = None


class SQLiteBackend(MemoryBackend):
    """
    SQLite implementation of the MemoryBackend interface.
    
    This provides the same behavior as the original hardcoded SQLite
    implementation in MemoryVault, but as a pluggable backend.
    
    Uses a single persistent connection per DB path (singleton) with WAL mode.
    Thread safety is ensured with a threading.Lock. Operations run in a
    thread pool via asyncio.to_thread for performance.
    
    Automatically re-initializes if DB is deleted mid-session (OperationalError)
    or if the DB file is recreated (detected by file creation time change).
    """
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        max_cached_sessions: Optional[int] = None,
        max_cached_docs: Optional[int] = None,
    ):
        if db_path is None:
            db_path = default_db_path()
            log.info("Using default memory database at %s", os.path.abspath(db_path))
        self.db_path = db_path
        self._initialized = False
        self._init_lock = None
        self._thread_lock = threading.Lock()
        self._conn = None
        self._file_creation_time = None
        # LRU caps for the per-session index cache. None means unbounded.
        self._max_cached_sessions = _resolve_cap(
            max_cached_sessions, "CYRRUS_INDEX_MAX_SESSIONS", DEFAULT_MAX_CACHED_SESSIONS
        )
        self._max_cached_docs = _resolve_cap(
            max_cached_docs, "CYRRUS_INDEX_MAX_DOCS", DEFAULT_MAX_CACHED_DOCS
        )
        # Per-session inverted index cache for retrieve_ranked(), LRU-ordered
        # (front = least-recently-used, end = most-recently-used):
        # session_id -> {"index": SessionFactIndex, "data_version": int}
        self._indexes: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._index_total_docs = 0
        self._index_lock = threading.Lock()
    
    def _get_init_lock(self) -> asyncio.Lock:
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        return self._init_lock
    
    def _get_file_creation_time(self):
        """Get the creation time of the DB file, or None if it doesn't exist."""
        try:
            return os.path.getctime(self.db_path)
        except OSError:
            return None
    
    def _connect(self):
        """Create a new database connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        # WAL mode for better concurrent performance
        conn.execute("PRAGMA journal_mode=WAL")
        # Synchronous=NORMAL is faster and still safe with WAL
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn
    
    def _get_connection(self):
        """Get or create the persistent connection."""
        if self._conn is None:
            self._conn = self._connect()
            self._file_creation_time = self._get_file_creation_time()
        return self._conn
    
    def _reset_connection(self):
        """Reset the connection (e.g., after DB deletion)."""
        if self._conn:
            try:
                self._conn.close()
            except:
                pass
            self._conn = None
        self._initialized = False
        self._file_creation_time = None
        with self._index_lock:
            self._indexes.clear()
            self._index_total_docs = 0

    def _invalidate_index(self, session_id: str):
        """Drop the cached index for a session after its facts change."""
        with self._index_lock:
            entry = self._indexes.pop(session_id, None)
            if entry is not None:
                self._index_total_docs -= entry["index"].corpus_size

    def _index_put(self, session_id: str, index: SessionFactIndex, data_version: int):
        """Insert/refresh a cached index as most-recently-used, then evict LRU
        entries until both caps are satisfied.

        Must be called with self._index_lock held. The just-inserted session is
        never evicted (even if it alone exceeds the doc cap) to avoid thrashing
        on a single oversized session; eviction stops once only it remains.
        """
        existing = self._indexes.pop(session_id, None)
        if existing is not None:
            self._index_total_docs -= existing["index"].corpus_size
        self._indexes[session_id] = {"index": index, "data_version": data_version}
        self._index_total_docs += index.corpus_size

        while len(self._indexes) > 1:
            over_sessions = (
                self._max_cached_sessions is not None
                and len(self._indexes) > self._max_cached_sessions
            )
            over_docs = (
                self._max_cached_docs is not None
                and self._index_total_docs > self._max_cached_docs
            )
            if not (over_sessions or over_docs):
                break
            _oldest_sid, oldest = self._indexes.popitem(last=False)
            self._index_total_docs -= oldest["index"].corpus_size
    
    def _check_file_recreated(self):
        """Check if the DB file has been recreated since last check."""
        current_ctime = self._get_file_creation_time()
        if current_ctime is None:
            # File doesn't exist
            if self._file_creation_time is not None:
                log.info("DB file deleted, will reinitialize on next operation")
                self._reset_connection()
                return True
            return False
        elif self._file_creation_time is not None and current_ctime != self._file_creation_time:
            # File was recreated (different creation time)
            log.info("DB file recreated, will reinitialize on next operation")
            self._reset_connection()
            return True
        return False
    
    async def init_db(self) -> None:
        """Initialize the SQLite database with schema and indexes."""
        # Check if file was recreated
        if self._check_file_recreated():
            self._initialized = False
        
        if self._initialized:
            return
        
        async with self._get_init_lock():
            if self._initialized:
                return
            
            def _init():
                conn = self._get_connection()
                try:
                    # Check if table exists
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
                    )
                    table_exists = cursor.fetchone() is not None
                    
                    if table_exists:
                        # Check if we need to migrate from old schema (without temporal columns)
                        cursor = conn.execute("PRAGMA table_info(facts)")
                        columns = [row[1] for row in cursor.fetchall()]
                        
                        if "valid_at" not in columns:
                            # Old schema - migrate to new temporal schema
                            log.info("Migrating facts table to temporal schema...")
                            conn.execute("""
                                CREATE TABLE facts_new (
                                    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
                                    session_id    TEXT NOT NULL,
                                    keyword       TEXT NOT NULL,
                                    value         TEXT,
                                    tokens        INTEGER,
                                    last_accessed REAL,
                                    valid_at      TEXT NOT NULL,
                                    invalid_at    TEXT
                                )
                            """)
                            # Migrate existing data
                            import datetime
                            now = datetime.datetime.now().isoformat()
                            conn.execute("""
                                INSERT INTO facts_new (session_id, keyword, value, tokens, last_accessed, valid_at)
                                SELECT session_id, keyword, value, tokens, last_accessed, ?
                                FROM facts
                            """, (now,))
                            conn.execute("DROP TABLE facts")
                            conn.execute("ALTER TABLE facts_new RENAME TO facts")
                    else:
                        # New database - create with temporal schema
                        conn.execute("""
                            CREATE TABLE facts (
                                rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
                                session_id    TEXT NOT NULL,
                                keyword       TEXT NOT NULL,
                                value         TEXT,
                                tokens        INTEGER,
                                last_accessed REAL,
                                valid_at      TEXT NOT NULL,
                                invalid_at    TEXT
                            )
                        """)
                    
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON facts(session_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_current ON facts(session_id, invalid_at) WHERE invalid_at IS NULL")
                    # Speeds up touch()/upsert() lookups by (session_id, keyword);
                    # without it each UPDATE scans every row of the session.
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_keyword ON facts(session_id, keyword)")
                    
                    conn.commit()
                finally:
                    pass  # Keep connection open for reuse
            
            await asyncio.to_thread(_init)
            self._initialized = True
    
    def _run_in_thread(self, operation):
        """Run a database operation in the thread pool with thread-safe connection access."""
        def _wrapped():
            with self._thread_lock:
                conn = self._get_connection()
                try:
                    return operation(conn)
                except sqlite3.OperationalError:
                    # Connection may be invalid (DB deleted), reset and re-raise
                    self._reset_connection()
                    raise
        return asyncio.to_thread(_wrapped)
    
    async def _execute_with_retry(self, operation):
        """Execute an operation with automatic retry on OperationalError (DB deleted)."""
        # Check if file was recreated before each operation
        if self._check_file_recreated():
            self._initialized = False
            await self.init_db()
        
        for attempt in range(2):
            try:
                return await self._run_in_thread(operation)
            except sqlite3.OperationalError as e:
                if attempt == 0:
                    log.warning("DB operation failed (%s), attempting to reinitialize...", e)
                    self._reset_connection()
                    await self.init_db()
                    continue
                raise
    
    async def upsert(
        self,
        session_id: str,
        keyword: str,
        value: str,
        tokens: int,
        max_facts_per_session: Optional[int],
        max_fact_value_length: int
    ) -> None:
        """Store or update a fact for a session with temporal tracking."""
        validate_session_id(session_id)
        validate_keyword(keyword)
        # Truncate value if needed
        if value and len(value) > max_fact_value_length:
            log.warning(
                "Fact '%s' (session %s) truncated from %d to %d chars.",
                keyword, session_id, len(value), max_fact_value_length,
            )
            value = value[:max_fact_value_length].rsplit(" ", 1)[0] + "..."
            tokens = min(tokens, len(value.split()))
        
        def _upsert(conn):
            # Check if there's a current fact for this (session_id, keyword)
            current = conn.execute(
                "SELECT rowid FROM facts WHERE session_id=? AND keyword=? AND invalid_at IS NULL",
                (session_id, keyword)
            ).fetchone()
            
            # Use a more precise timestamp to avoid collisions
            import datetime
            now = datetime.datetime.now().isoformat()
            
            if current:
                # Invalidate the old fact
                conn.execute(
                    "UPDATE facts SET invalid_at=? WHERE rowid=?",
                    (now, current[0])
                )
            
            # Insert the new fact as current
            conn.execute(
                "INSERT INTO facts (session_id, keyword, value, tokens, last_accessed, valid_at) VALUES (?,?,?,?,?,?)",
                (session_id, keyword, value, tokens, time.time(), now),
            )
            
            if max_facts_per_session is not None:
                total = conn.execute(
                    "SELECT COUNT(*) FROM facts WHERE session_id=?",
                    (session_id,)
                ).fetchone()[0]
                if total > max_facts_per_session:
                    overflow = total - max_facts_per_session
                    # Oldest superseded rows go first; only then oldest active ones.
                    cursor = conn.execute("""
                        DELETE FROM facts WHERE rowid IN (
                            SELECT rowid FROM facts
                            WHERE session_id=? AND invalid_at IS NOT NULL
                            ORDER BY valid_at ASC, rowid ASC LIMIT ?
                        )
                    """, (session_id, overflow))
                    overflow -= cursor.rowcount
                    if overflow > 0:
                        conn.execute("""
                            DELETE FROM facts WHERE rowid IN (
                                SELECT rowid FROM facts
                                WHERE session_id=? AND invalid_at IS NULL
                                ORDER BY valid_at ASC, rowid ASC LIMIT ?
                            )
                        """, (session_id, overflow))
            
            conn.commit()
            self._invalidate_index(session_id)
        
        await self._execute_with_retry(_upsert)
    
    async def retrieve_current(self, session_id: str, limit: Optional[int] = 100) -> List[tuple]:
        """Retrieve current facts for a session (invalid_at IS NULL).

        limit=None returns every active fact so callers that rank by relevance
        (BM25) can consider the whole set rather than only the most-recently
        -accessed rows. An integer limit keeps the recency-bounded behavior.
        """
        validate_session_id(session_id)

        def _retrieve(conn):
            if limit is None:
                return conn.execute(
                    "SELECT keyword, value, tokens FROM facts "
                    "WHERE session_id=? AND invalid_at IS NULL ORDER BY last_accessed DESC",
                    (session_id,),
                ).fetchall()
            return conn.execute(
                "SELECT keyword, value, tokens FROM facts "
                "WHERE session_id=? AND invalid_at IS NULL ORDER BY last_accessed DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()

        return await self._execute_with_retry(_retrieve)

    def _get_or_build_index(self, conn, session_id: str) -> SessionFactIndex:
        """Return the cached index for a session, rebuilding it when absent or
        stale. Shared by retrieve_ranked() and the background warm-up.

        Reads PRAGMA data_version BEFORE the SELECT so a concurrent external
        commit forces a rebuild on the next call (never the reverse). Must be
        called while holding the connection (inside _execute_with_retry).
        """
        current_dv = conn.execute("PRAGMA data_version").fetchone()[0]
        with self._index_lock:
            entry = self._indexes.get(session_id)
            if entry is not None and entry["data_version"] == current_dv:
                self._indexes.move_to_end(session_id)
                return entry["index"]
        rows = conn.execute(
            "SELECT keyword, value, tokens FROM facts "
            "WHERE session_id=? AND invalid_at IS NULL ORDER BY last_accessed DESC",
            (session_id,),
        ).fetchall()
        index = SessionFactIndex([(r[0], r[1], r[2]) for r in rows])
        with self._index_lock:
            self._index_put(session_id, index, current_dv)
        return index

    async def retrieve_ranked(
        self,
        session_id: str,
        user_input: str,
        limit: int = 3,
        score_threshold: float = 0.0,
    ):
        """BM25-rank all active facts for a session using a cached
        per-session inverted index.

        Rankings are identical to bm25_rank_facts over
        retrieve_current(limit=None). The index is rebuilt only when the
        session's facts change (writes invalidate it directly; writes from
        other processes/connections are detected via PRAGMA data_version).
        """
        validate_session_id(session_id)

        def _work(conn):
            index = self._get_or_build_index(conn, session_id)
            return index.rank(
                user_input, limit=limit, score_threshold=score_threshold
            )

        return await self._execute_with_retry(_work)

    def warm_recent_sync(self, limit: int = 8) -> int:
        """Synchronously pre-build indexes for the most-recently-used sessions.

        Designed to run on a plain background thread at gateway startup. It
        holds the same connection lock as request-path operations (so it
        serializes with them) and touches no asyncio primitives, so it is safe
        alongside the gateway's per-request ``asyncio.run`` loops. Best-effort:
        returns the number of sessions warmed and never raises. If the schema
        does not exist yet, it does nothing and the first request initializes
        the DB as usual.
        """
        if limit <= 0:
            return 0
        try:
            with self._thread_lock:
                conn = self._get_connection()
                try:
                    rows = conn.execute(
                        "SELECT session_id FROM facts WHERE invalid_at IS NULL "
                        "GROUP BY session_id ORDER BY MAX(last_accessed) DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    return 0
                warmed = 0
                for row in rows:
                    sid = row[0]
                    try:
                        validate_session_id(sid)
                        self._get_or_build_index(conn, sid)
                        warmed += 1
                    except Exception as exc:  # pragma: no cover - defensive
                        log.debug("warm_index(%s) skipped: %s", sid, exc)
                return warmed
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("warm_recent_sync skipped: %s", exc)
            return 0

    async def touch(self, session_id: str, keywords: List[str]) -> None:
        """Update last_accessed timestamp for specified facts."""
        validate_session_id(session_id)
        for kw in keywords:
            validate_keyword(kw)

        def _touch(conn):
            now = time.time()
            conn.executemany(
                "UPDATE facts SET last_accessed=? WHERE session_id=? AND keyword=?",
                [(now, session_id, kw) for kw in keywords],
            )
            conn.commit()
            # Do NOT advance the cached data_version stamp here. A connection's
            # own commit never bumps its own data_version (only another
            # connection's commit does), so the build-time stamp stays valid
            # across touch when nothing external changed -- and when something
            # DID change externally, leaving the stamp alone forces the next
            # retrieve_ranked to rebuild and observe it. The old behaviour
            # re-stamped the post-commit data_version onto the cached index,
            # which absorbed a concurrent external supersede without a rebuild
            # and pinned retrieval to the stale value (P0).

        await self._execute_with_retry(_touch)
    
    async def delete_session(self, session_id: str) -> int:
        """Delete all facts for a session."""
        validate_session_id(session_id)

        def _delete(conn):
            cursor = conn.execute(
                "DELETE FROM facts WHERE session_id=?",
                (session_id,)
            )
            rowcount = cursor.rowcount
            conn.commit()
            self._invalidate_index(session_id)
            return rowcount
        
        return await self._execute_with_retry(_delete)
    
    async def get_fact_history(
        self,
        session_id: str,
        keyword: str
    ) -> List[Dict[str, Any]]:
        """Retrieve the full timeline of a fact."""
        validate_session_id(session_id)
        validate_keyword(keyword)

        def _history(conn):
            rows = conn.execute(
                "SELECT value, tokens, valid_at, invalid_at FROM facts "
                "WHERE session_id=? AND keyword=? ORDER BY valid_at ASC",
                (session_id, keyword)
            ).fetchall()
            
            return [
                {
                    "value": row[0],
                    "tokens": row[1],
                    "valid_at": row[2],
                    "invalid_at": row[3],
                }
                for row in rows
            ]
        
        return await self._execute_with_retry(_history)
    
    async def close(self) -> None:
        """Close the persistent connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
        with self._index_lock:
            self._indexes.clear()
            self._index_total_docs = 0

    async def forget_fact(self, session_id: str, key: str) -> bool:
        """Physically delete ALL rows for (session_id, key), including superseded versions."""
        validate_session_id(session_id)
        validate_keyword(key)

        def _forget(conn):
            cursor = conn.execute(
                "DELETE FROM facts WHERE session_id=? AND keyword=?",
                (session_id, key),
            )
            rowcount = cursor.rowcount
            conn.commit()
            self._invalidate_index(session_id)
            return rowcount > 0

        return await self._execute_with_retry(_forget)

    async def forget_session(self, session_id: str) -> int:
        """Delete all facts for a session. Returns the number of facts deleted."""
        validate_session_id(session_id)

        def _forget(conn):
            cursor = conn.execute(
                "DELETE FROM facts WHERE session_id=?",
                (session_id,),
            )
            rowcount = cursor.rowcount
            conn.commit()
            self._invalidate_index(session_id)
            return rowcount

        return await self._execute_with_retry(_forget)

    async def export_facts(
        self, session_id: str, include_superseded: bool = False
    ) -> list[dict]:
        """Export facts for a session as JSON-serializable dicts, ordered by creation."""
        validate_session_id(session_id)

        def _export(conn):
            if include_superseded:
                rows = conn.execute(
                    "SELECT keyword, value, valid_at, invalid_at FROM facts "
                    "WHERE session_id=? ORDER BY valid_at ASC, rowid ASC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT keyword, value, valid_at, invalid_at FROM facts "
                    "WHERE session_id=? AND invalid_at IS NULL "
                    "ORDER BY valid_at ASC, rowid ASC",
                    (session_id,),
                ).fetchall()

            return [
                {
                    "key": row[0],
                    "value": row[1],
                    "created": row[2],
                    "invalid_at": row[3],
                }
                for row in rows
            ]

        return await self._execute_with_retry(_export)

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions with their active fact counts."""
        def _list(conn):
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
            )
            if cursor.fetchone() is None:
                return []
            rows = conn.execute(
                "SELECT session_id, COUNT(CASE WHEN invalid_at IS NULL THEN 1 END) "
                "FROM facts GROUP BY session_id ORDER BY session_id ASC"
            ).fetchall()
            return [
                {
                    "session_id": row[0],
                    "fact_count": row[1],
                    "active_facts": row[1],
                    "id": row[0],
                }
                for row in rows
            ]

        return await self._execute_with_retry(_list)

    def __del__(self):
        """Ensure connection is closed when backend is garbage collected."""
        if self._conn:
            try:
                self._conn.close()
            except:
                pass
            self._conn = None