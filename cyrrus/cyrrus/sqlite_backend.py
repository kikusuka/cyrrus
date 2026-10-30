"""
SQLite backend implementation for MemoryVault.

This is the default zero-dependency backend, wrapping the existing
SQLite logic that was previously hardcoded in MemoryVault.
from __future__ import annotations
import sqlite3
import time
import logging
import os
import sys
from typing import List, Dict, Any, Optional
import asyncio
import threading
from .backend import MemoryBackend, validate_session_id, validate_keyword


log = logging.getLogger("cyrrus.sqlite_backend")


def default_db_path() -> str:
    """Resolve the default memory database path.

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


def get_backend(db_path: str) -> "SQLiteBackend":
    """Get or create a backend instance for the given DB path (singleton per path)."""
    with _registry_lock:
        if db_path not in _backend_registry:
            _backend_registry[db_path] = SQLiteBackend(db_path)
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
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = default_db_path()
            log.info("Using default memory database at %s", os.path.abspath(db_path))
        self.db_path = db_path
        self._initialized = False
        self._init_lock = None
        self._thread_lock = threading.Lock()
        self._conn = None
        self._file_creation_time = None
    
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
        
        await self._execute_with_retry(_upsert)
    
    async def retrieve_current(self, session_id: str, limit: int = 100) -> List[tuple]:
        """Retrieve current facts for a session (invalid_at IS NULL)."""
        validate_session_id(session_id)

        def _retrieve(conn):
            results = conn.execute(
                "SELECT keyword, value, tokens FROM facts "
                "WHERE session_id=? AND invalid_at IS NULL ORDER BY last_accessed DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return results
        
        return await self._execute_with_retry(_retrieve)
    
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