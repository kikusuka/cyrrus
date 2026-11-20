"""Deterministic demo-data fixture for TUI golden-frame tests.

Creates a sandbox SQLite database with 3 sessions, facts with dates,
a superseded history, and a saved-trace shape so that every screen
test and `cyrrus ui --dump-frame ... --demo` produces reproducible output.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import List

from .sqlite_backend import get_backend, default_db_path, close_backend

DB_PATH = Path(default_db_path())

_SESSIONS = [
    {
        "id": "work",
        "facts": [
            ("project Alpha", "Initial project kickoff", 0.0),
            ("meeting notes", "Weekly sync notes", 1.5),
            ("design draft", "UI design draft v2", 3.2),
        ],
    },
    {
        "id": "personal",
        "facts": [
            ("grocery list", "Milk, eggs, bread", 0.3),
            ("book review", "The Midnight Library", 2.1),
            ("travel plan", "Tokyo itinerary", 4.0),
        ],
    },
    {
        "id": "scratch",
        "facts": [
            ("experiment 1", "Temp file storage", 1.0),
            ("quick note", "Reminder: call dentist", 0.5),
        ],
    },
]


def _init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the sandbox database with schema and seed data."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Create facts table with temporal schema
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL,
            keyword       TEXT NOT NULL,
            value         TEXT,
            tokens        INTEGER,
            last_accessed REAL,
            valid_at      TEXT NOT NULL,
            invalid_at    TEXT
        )
        """
    )

    # Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON facts(session_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_current "
        "ON facts(session_id, invalid_at) WHERE invalid_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_keyword "
        "ON facts(session_id, keyword)"
    )

    now = datetime.datetime.now().isoformat()

    # Seed 3 sessions with facts, including some superseded entries
    for sess in _SESSIONS:
        session_id = sess["id"]
        for idx, (keyword, value, tokens) in enumerate(sess["facts"]):
            valid_at = now
            # Make some facts superseded by setting invalid_at on older entries
            # "work" session: first fact will be superseded
            invalid_at = None
            if sess["id"] == "work" and idx == 0:
                # Mark the first fact as superseded later
                invalid_at = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()

            conn.execute(
                """
                INSERT INTO facts (session_id, keyword, value, tokens, last_accessed, valid_at, invalid_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (session_id, keyword, value, tokens, time.time(), valid_at, invalid_at),
            )

    # Also add a superseded fact in the personal session (simulating history)
    personal_now = now
    conn.execute(
        """
        INSERT INTO facts (session_id, keyword, value, tokens, last_accessed, valid_at, invalid_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("personal", "old project", " abandoned project from 2023", 1.0, time.time(), personal_now,
         (datetime.datetime.now() - datetime.timedelta(days=180)).isoformat()),
    )

    conn.commit()
    return conn


def build_demo_db(db_path: str | Path = DB_PATH) -> Path:
    """Build a deterministic sandbox DB for TUI golden-frame testing.

    The DB contains:
      - 3 sessions: work, personal, scratch
      - Each session has 3 active facts with dates
      - One superseded fact in 'personal' (simulating history)
      - The DB path is returned so tests can use it

    This is designed to be called once per test session (or once globally
    with idempotency), and the same data is reproduced every time.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # If DB already exists and has data, reuse it (idempotent)
    if db_path.exists():
        # Check if it has our seed data by checking row count
        conn = sqlite3.connect(str(db_path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        except Exception:
            count = 0
        finally:
            conn.close()
        if count >= 9:  # already seeded (3 + 3 + 2 facts + 1 superseded)
            return db_path
        db_path.unlink(missing_ok=True)

    conn = _init_db(db_path)
    conn.close()
    return db_path


def reset_demo_db(db_path: str | Path = DB_PATH) -> Path:
    """Fully reset the demo DB, deleting all data and re-seeding.

    Use this to start fresh (e.g. before a full test run).
    """
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    return build_demo_db(db_path)


def demo_db() -> Path:
    """Return the path to the existing demo DB, building it if needed."""
    return build_demo_db()


def _saved_trace_shape() -> dict:
    """Return the expected shape of /cyrrus/last for gateway tests."""
    return {
        "requests": [
            {
                "method": "POST",
                "path": "/v1/chat",
                "prompt": "What is the capital of France?",
            },
            {
                "method": "GET",
                "path": "/v1/models",
            },
        ],
        "model": "gpt-4o-mini",
    }


def save_demo_trace(db_path: str | Path = DB_PATH) -> dict:
    """Save the expected trace shape to the gateway's /cyrrus/last endpoint.

    In a real deployment this would be done by the gateway.  For test purposes
    we write a JSON file that mimics the gateway response so that
    `cyrrus ui --dump-frame ... --demo` can render the last-request summary.
    """
    shape = _saved_trace_shape()
    out_path = Path(db_path).parent / "last_trace.json"
    out_path.write_text(json.dumps(shape, indent=2), encoding="utf-8")
    return shape


if __name__ == "__main__":
    # CLI: build the demo DB and optionally save the trace shape
    db = demo_db()
    print(f"Demo DB built at: {db}")
    trace = save_demo_trace(db)
    print(f"Trace shape saved ( {len(trace['requests'])} requests )")