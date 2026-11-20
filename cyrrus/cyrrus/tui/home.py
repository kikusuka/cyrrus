"""Home screen widget for the cyrrus Textual UI.

Ported from the Breezy Trace design study: SESSIONS panel with facts/30d ramp,
OVERVIEW panel, empty-state, and footer key hints (q/?/o/n/Delete/r/Esc/1-5).
"""

from __future__ import annotations

import datetime
import sqlite3
import time
from typing import List, Tuple

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static, TabbedContent, TabPane

from . import theme, widgets
from .theme import density_ramp


NARROW_WIDTH = 80
WIDE_WIDTH = 100

# Fixed path for the demo DB used by the home screen
_DEMO_DB_PATH = Path(__file__).resolve().parents[3] / "tests" / "golden" / "_demo.db"


def _init_demo_db(db_path: Path) -> None:
    """Initialize the demo DB with seed data if it doesn't exist."""
    if db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
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
    # 3 sessions with facts
    sessions = {
        "work": [
            ("project Alpha", "Initial project kickoff", 0.0),
            ("meeting notes", "Weekly sync notes", 1.5),
            ("design draft", "UI design draft v2", 3.2),
        ],
        "personal": [
            ("grocery list", "Milk, eggs, bread", 0.3),
            ("book review", "The Midnight Library", 2.1),
            ("travel plan", "Tokyo itinerary", 4.0),
        ],
        "scratch": [
            ("experiment 1", "Temp file storage", 1.0),
            ("quick note", "Reminder: call dentist", 0.5),
        ],
    }
    for sid, facts in sessions.items():
        for idx, (keyword, value, tokens) in enumerate(facts):
            valid_at = now
            invalid_at = None
            # Mark first fact of 'work' as superseded
            if sid == "work" and idx == 0:
                invalid_at = (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat()
            conn.execute(
                """
                INSERT INTO facts (session_id, keyword, value, tokens, last_accessed, valid_at, invalid_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (sid, keyword, value, tokens, time.time(), valid_at, invalid_at),
            )
        # Add superseded fact in personal session
        if sid == "personal":
            conn.execute(
                """
                INSERT INTO facts (session_id, keyword, value, tokens, last_accessed, valid_at, invalid_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                ("personal", "old project",
                 " abandoned project from 2023", 1.0, time.time(), now,
                 (datetime.datetime.now() - datetime.timedelta(days=180)).isoformat()),
            )
    conn.commit()
    conn.close()


def _session_summary(sess_id: str, db_path) -> Tuple[int, int]:
    """Return (active_facts, total_facts) for a session."""
    conn = sqlite3.connect(str(db_path))
    active = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE session_id=? AND invalid_at IS NULL",
        (sess_id,),
    ).fetchone()[0]
    total = conn.execute(
        "SELECT COUNT(*) FROM facts WHERE session_id=?",
        (sess_id,),
    ).fetchone()[0]
    conn.close()
    return active, total


def _format_30day_ramp(values: List[float]) -> str:
    """Format a 30-day ramp using the monochrome density ramp."""
    return density_ramp(values, maximum=max(values) if values else 1)


_SESSION_RAMP_MAP = {
    "work": [1.0, 0.5, 0.2],
    "personal": [0.8, 0.6, 0.4],
    "scratch": [0.6, 0.4, 0.2],
}


class HomeApp(App):
    """Home screen with SESSIONS panel, OVERVIEW panel, empty-state, and footer."""

    CSS = theme.theme_css() + """
    HomeApp {
        layers: base;
    }
    .home-panel {
        border: round #808080;
        background: $background;
        color: $foreground;
        padding: 1 2;
    }
    .home-panel:focus-within {
        border: round $foreground;
    }
    .panel-title {
        color: #808080;
        text-style: bold;
        margin-bottom: 1;
    }
    .muted {
        color: #808080;
        text-style: dim;
    }
    .tab-bar {
        height: 1;
        background: $surface;
    }
    .tab-bar .tab {
        color: #808080;
    }
    .tab-bar .tab.active {
        color: $primary;
        text-style: bold underline;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
        ("o", "add", "Add session"),
        ("n", "new", "New session"),
        ("d", "forget", "Forget session"),
        ("r", "refresh", "Refresh"),
        ("1", "tab-1", "Switch to session 1"),
        ("2", "tab-2", "Switch to session 2"),
        ("3", "tab-3", "Switch to session 3"),
        ("escape", "lobby", "Lobby"),
    ]

    def __init__(self) -> None:
        super().__init__()
        _init_demo_db(_DEMO_DB_PATH)
        self.db_path = _DEMO_DB_PATH
        # Pre-create placeholder static widgets; _load_and_render will update their content
        self._sessions_static = Static("", classes="home-panel")
        self._overview_static = Static("", classes="home-panel")

    def compose(self) -> ComposeResult:
        yield Static("cyrrus · by Breezy Labs", id="header")
        with TabbedContent(id="main-tabs"):
            with TabPane("Sessions", id="sessions-pane"):
                yield self._sessions_static
            with TabPane("Overview", id="overview-pane"):
                yield self._overview_static
        yield widgets.KeyHints(widgets.HOME_HINTS)

    def on_mount(self) -> None:
        self._load_and_render()

    def _load_and_render(self) -> None:
        """Load demo DB data and render both panels."""
        db = self.db_path

        # --- SESSIONS panel ---
        rows: List[str] = []
        for sid in ["work", "personal", "scratch"]:
            active, total = _session_summary(sid, db)
            ramp_values = _SESSION_RAMP_MAP.get(sid, [0.5])
            ramp = _format_30day_ramp(ramp_values)
            rows.append(f"  {sid:12s}  {active} active  {ramp}")

        if rows:
            sessions_text = "Sessions\n" + "\n".join(rows)
        else:
            sessions_text = "No sessions found. Press 'o' to add or 'n' to new."

        self._sessions_static.update(sessions_text)

        # --- OVERVIEW panel ---
        active_sessions = sum(
            _session_summary(sid, db)[0] for sid in ["work", "personal", "scratch"]
        )
        total_facts = sum(
            _session_summary(sid, db)[1] for sid in ["work", "personal", "scratch"]
        )
        overview_text = (
            f"Overview\n"
            f"Active sessions: {active_sessions}\n"
            f"Total facts: {total_facts}\n"
            f"30-day ramp: monitoring engagement"
        )
        self._overview_static.update(overview_text)

    def action_quit(self) -> None:
        self.exit()

    def action_help(self) -> None:
        self.notify("Home help: q=quit, ?=help, o=add, n=new, d=forget, r=refresh, 1-3=switch session, esc=lobby")

    def action_add(self) -> None:
        self.notify("Add session (not yet implemented)")

    def action_new(self) -> None:
        self.notify("New session (not yet implemented)")

    def action_forget(self) -> None:
        self.notify("Forget session (not yet implemented)")

    def action_refresh(self) -> None:
        self._load_and_render()

    def action_tab_1(self) -> None:
        self.notify("Switch to session work")

    def action_tab_2(self) -> None:
        self.notify("Switch to session personal")

    def action_tab_3(self) -> None:
        self.notify("Switch to session scratch")