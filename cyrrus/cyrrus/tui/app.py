"""Runnable Textual application for ``cyrrus ui``.

The UI is optional: importing this module requires the ``ui`` extra, while
:mod:`cyrrus.tui` and the core package stay importable without Textual.

Data access is deliberately kept off the UI thread.  Every database or
filesystem call runs in a worker through :func:`asyncio.to_thread`; the UI
only renders the result it receives back on the event loop.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import (
    ContentSwitcher,
    DataTable,
    Input,
    Static,
    TabbedContent,
    TabPane,
    Tabs,
)

from .. import tools as core_tools
from ..config import (
    DEFAULTS,
    get_project_config_path,
    load_config,
    save_config_file,
    validate_config,
)
from . import theme, widgets
from ..demo_fixture import build_demo_db, save_demo_trace
from .intro import IntroData, IntroScreen
from .theme import density_ramp


DEFAULT_MIN_RELATIVE_SCORE = float(DEFAULTS["memory"]["min_relative_score"])
RAMPS = {
    "work": [1.0, 0.5, 0.2],
    "personal": [0.8, 0.6, 0.4],
    "scratch": [0.6, 0.4, 0.2],
}

HOME_VIEW_HINTS = [
    widgets.KeyHint("q", "Quit"),
    widgets.KeyHint("?", "Help"),
    widgets.KeyHint("Enter", "Open"),
    widgets.KeyHint("r", "Refresh"),
]
SESSION_VIEW_HINTS = [
    widgets.KeyHint("q", "Quit"),
    widgets.KeyHint("?", "Help"),
    widgets.KeyHint("1-5", "Tabs"),
    widgets.KeyHint("/", "Search"),
    widgets.KeyHint("n", "New"),
    widgets.KeyHint("del", "Forget"),
    widgets.KeyHint("e", "Export"),
    widgets.KeyHint("s", "Setting"),
    widgets.KeyHint("esc", "Back"),
]


@dataclass(frozen=True)
class SessionEntry:
    session_id: str
    active_facts: int
    last_active: str
    ramp: str


@dataclass(frozen=True)
class FactEntry:
    key: str
    value: str
    created: str
    invalid_at: Optional[str] = None
    score: Optional[float] = None


@dataclass(frozen=True)
class HomeData:
    sessions: List[SessionEntry]
    active_facts: int


def _short_time(value: Any) -> str:
    if not value:
        return "\u2014"
    text = str(value).replace("T", " ")
    return text[:16]


def _clip(value: Any, width: int = 42) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= width:
        return text
    return text[: width - 1] + "\u2026"


def parse_min_relative_score(value: Any) -> Tuple[Optional[float], Optional[str]]:
    """Return ``(number, None)`` or ``(None, error message)``."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None, "memory.min_relative_score must be a number between 0 and 1"
    if not 0.0 <= number <= 1.0:
        return None, "memory.min_relative_score must be a number between 0 and 1"
    return number, None


class DataService:
    """Thin, synchronous adapter around the existing tools layer.

    Callers use it from a worker thread.  Demo mode merely points the same
    tools at a fixture database; it never takes a different code path.
    """

    def __init__(
        self,
        *,
        demo: bool = False,
        db_path: Optional[Path] = None,
        config_path: Optional[Path] = None,
        export_dir: Optional[Path] = None,
    ) -> None:
        self.demo = demo
        self.db_path = str(db_path) if db_path is not None else None
        self.config_path = Path(config_path) if config_path else get_project_config_path()
        self.export_dir = Path(export_dir) if export_dir else Path.cwd()

    # -- reads ------------------------------------------------------------
    def home_data(self) -> HomeData:
        result = core_tools.sessions(db_path=self.db_path)
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "could not list sessions")

        entries: List[SessionEntry] = []
        for raw in result.get("sessions", []):
            session_id = raw.get("session_id") or raw.get("id") or ""
            if not session_id:
                continue
            active = int(raw.get("active_facts") or raw.get("fact_count") or 0)
            last_active = ""
            facts = core_tools.memory_list(session=session_id, db_path=self.db_path)
            if facts.get("success"):
                created = [f.get("created") for f in facts.get("facts", []) if f.get("created")]
                if created:
                    last_active = _short_time(max(created))
            entries.append(
                SessionEntry(
                    session_id=session_id,
                    active_facts=active,
                    last_active=last_active or "\u2014",
                    ramp=density_ramp(RAMPS.get(session_id, [0.5])),
                )
            )
        entries.sort(key=lambda entry: entry.session_id)
        return HomeData(
            sessions=entries,
            active_facts=sum(entry.active_facts for entry in entries),
        )

    def facts(self, session_id: str, include_superseded: bool = False) -> List[FactEntry]:
        result = core_tools.memory_list(
            session=session_id,
            include_superseded=include_superseded,
            db_path=self.db_path,
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "could not list facts")
        entries = []
        for raw in result.get("facts", []):
            entries.append(
                FactEntry(
                    key=str(raw.get("key") or ""),
                    value=str(raw.get("value") or ""),
                    created=str(raw.get("created") or ""),
                    invalid_at=raw.get("invalid_at"),
                )
            )
        return entries

    def history(self, session_id: str) -> List[FactEntry]:
        return [fact for fact in self.facts(session_id, include_superseded=True) if fact.invalid_at]

    def search(self, session_id: str, query: str) -> List[FactEntry]:
        result = core_tools.memory_search(
            session=session_id,
            query=query,
            limit=50,
            db_path=self.db_path,
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "search failed")
        return [
            FactEntry(
                key=str(raw.get("key") or ""),
                value=str(raw.get("value") or ""),
                created="",
                score=raw.get("score"),
            )
            for raw in result.get("results", [])
        ]

    def trace(self) -> Optional[Dict[str, Any]]:
        if self.db_path:
            saved = Path(self.db_path).parent / "last_trace.json"
            if saved.exists():
                try:
                    return json.loads(saved.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8787/cyrrus/last", timeout=1.0
            ) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError):
            return None

    # -- writes -----------------------------------------------------------
    def add_fact(self, session_id: str, key: str, value: str) -> Dict[str, Any]:
        return core_tools.memory_add(
            session=session_id, key=key, value=value, db_path=self.db_path
        )

    def forget(self, session_id: str, key: str) -> Dict[str, Any]:
        return core_tools.memory_forget(
            session=session_id, key=key, db_path=self.db_path
        )

    def export_path(self, session_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in session_id)
        return self.export_dir / ("cyrrus-%s-facts.json" % (safe or "session"))

    def export(self, session_id: str, path: Path) -> Dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        return core_tools.memory_export(
            session=session_id, path=str(path), db_path=self.db_path
        )

    # -- settings ---------------------------------------------------------
    def read_min_relative_score(self) -> float:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                value = data.get("memory", {}).get(
                    "min_relative_score", DEFAULT_MIN_RELATIVE_SCORE
                )
                number, _error = parse_min_relative_score(value)
                if number is not None:
                    return number
            except (OSError, ValueError, AttributeError):
                pass
        if not self.demo:
            try:
                value = load_config().get("memory", {}).get(
                    "min_relative_score", DEFAULT_MIN_RELATIVE_SCORE
                )
                number, _error = parse_min_relative_score(value)
                if number is not None:
                    return number
            except Exception:  # noqa: BLE001 - a UI read must never crash the app
                pass
        return DEFAULT_MIN_RELATIVE_SCORE

    def write_min_relative_score(self, value: Any) -> float:
        number, error = parse_min_relative_score(value)
        if error:
            raise ValueError(error)
        data: Dict[str, Any] = {}
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, ValueError):
                data = {}
        memory = data.setdefault("memory", {})
        if not isinstance(memory, dict):
            memory = {}
            data["memory"] = memory
        memory["min_relative_score"] = number
        validate_config(data)
        save_config_file(data, self.config_path)
        return float(number)


class HomeView(Vertical):
    """Sessions panel; Enter opens the focused row."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, service: DataService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.sessions: List[SessionEntry] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="home-summary", classes="muted")
        with widgets.Panel("SESSIONS", id="sessions-panel"):
            yield widgets.MonoTable(id="sessions-table")
            yield Static(
                "No sessions yet. Facts appear here after cyrrus records them.",
                id="sessions-empty",
                classes="empty-state",
            )
        yield widgets.KeyHints(HOME_VIEW_HINTS)

    def on_mount(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.query_one("#home-summary", Static).update("Loading sessions\u2026")
        self.run_worker(self._load(), group="home", exclusive=True)

    async def _load(self) -> None:
        try:
            data = await asyncio.to_thread(self.service.home_data)
        except Exception as exc:  # noqa: BLE001 - show the failure, keep the UI alive
            self.query_one("#home-summary", Static).update("Could not load sessions: %s" % exc)
            self.app.toast("Could not load sessions")
            return
        self.apply(data)

    def apply(self, data: HomeData) -> None:
        self.sessions = data.sessions
        summary = "%d session%s \u00b7 %d active fact%s" % (
            len(data.sessions),
            "" if len(data.sessions) == 1 else "s",
            data.active_facts,
            "" if data.active_facts == 1 else "s",
        )
        self.query_one("#home-summary", Static).update(summary)
        table = self.query_one("#sessions-table", widgets.MonoTable)
        empty = self.query_one("#sessions-empty", Static)
        table.clear(columns=True)
        if not data.sessions:
            table.display = False
            empty.display = True
            self.focus()
            return
        table.display = True
        empty.display = False
        table.add_columns("SESSION", "FACTS", "LAST ACTIVE", "30 DAYS")
        for entry in data.sessions:
            table.add_row(
                entry.session_id,
                str(entry.active_facts),
                entry.last_active,
                entry.ramp,
                key=entry.session_id,
            )
        table.focus()
        if table.row_count:
            table.move_cursor(row=0)

    def focus_home(self) -> None:
        if self.sessions:
            self.query_one("#sessions-table", widgets.MonoTable).focus()
        else:
            self.focus()

    def action_refresh(self) -> None:
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sessions-table":
            return
        session_id = str(event.row_key.value)
        if session_id:
            self.app.open_session(session_id)


class SessionView(Vertical):
    """Overview, Facts, Trace, History and Settings for one session."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("1", "tab_1", "Overview"),
        Binding("2", "tab_2", "Facts"),
        Binding("3", "tab_3", "Trace"),
        Binding("4", "tab_4", "History"),
        Binding("5", "tab_5", "Settings"),
        Binding("slash", "search", "Search"),
        Binding("n", "add_fact", "New fact"),
        Binding("delete", "forget_fact", "Forget"),
        Binding("e", "export", "Export"),
        Binding("s", "edit_setting", "Setting"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, service: DataService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.session_id: Optional[str] = None
        self._facts: List[FactEntry] = []
        self._visible_keys: List[str] = []
        self._min_relative_score = DEFAULT_MIN_RELATIVE_SCORE
        self._search_visible = False

    def compose(self) -> ComposeResult:
        yield Static("", id="session-header")
        with TabbedContent(id="session-tabs"):
            with TabPane("Overview", id="tab-overview"):
                yield Static("", id="overview-body", classes="panel-body")
            with TabPane("Facts", id="tab-facts"):
                yield Input(placeholder="Search facts, then press Enter", id="facts-search")
                yield widgets.MonoTable(id="facts-table")
                yield Static("", id="facts-empty", classes="empty-state")
            with TabPane("Trace", id="tab-trace"):
                yield Static("", id="trace-body", classes="panel-body")
            with TabPane("History", id="tab-history"):
                yield widgets.MonoTable(id="history-table")
                yield Static("", id="history-empty", classes="empty-state")
            with TabPane("Settings", id="tab-settings"):
                yield Static("", id="settings-body", classes="panel-body")
        yield widgets.KeyHints(SESSION_VIEW_HINTS)

    def on_mount(self) -> None:
        self.query_one("#facts-search", Input).display = False

    @property
    def tabs(self) -> TabbedContent:
        return self.query_one("#session-tabs", TabbedContent)

    def open(self, session_id: str) -> None:
        self.session_id = session_id
        self._search_visible = False
        search = self.query_one("#facts-search", Input)
        search.value = ""
        search.display = False
        self.query_one("#session-header", Static).update("cyrrus \u00b7 session %s" % session_id)
        self.tabs.active = "tab-overview"
        self.query_one("#overview-body", Static).update("Loading session\u2026")
        self.query_one("#trace-body", Static).update("Loading trace\u2026")
        self.query_one("#settings-body", Static).update("Loading setting\u2026")
        self._clear_facts()
        self._clear_history()
        self.reload()
        self._focus_active()

    def reload(self) -> None:
        if not self.session_id:
            return
        self.run_worker(self._load(self.session_id), group="session", exclusive=True)

    async def _load(self, session_id: str) -> None:
        try:
            facts = await asyncio.to_thread(self.service.facts, session_id)
            history = await asyncio.to_thread(self.service.history, session_id)
            trace = await asyncio.to_thread(self.service.trace)
            setting = await asyncio.to_thread(self.service.read_min_relative_score)
        except Exception as exc:  # noqa: BLE001 - render the error, keep the app alive
            self.query_one("#overview-body", Static).update("Could not load session: %s" % exc)
            self.app.toast("Could not load session")
            return
        if self.session_id != session_id:
            return
        self._facts = facts
        self._min_relative_score = setting
        self._render_overview(facts, history)
        self._fill_facts(facts)
        self._fill_history(history)
        self._render_trace(trace)
        self._render_settings()

    # -- rendering --------------------------------------------------------
    def _clear_facts(self) -> None:
        table = self.query_one("#facts-table", widgets.MonoTable)
        table.clear(columns=True)
        self._visible_keys = []
        self.query_one("#facts-empty", Static).update("")

    def _clear_history(self) -> None:
        table = self.query_one("#history-table", widgets.MonoTable)
        table.clear(columns=True)
        self.query_one("#history-empty", Static).update("")

    def _fill_facts(self, facts: Sequence[FactEntry]) -> None:
        table = self.query_one("#facts-table", widgets.MonoTable)
        empty = self.query_one("#facts-empty", Static)
        table.clear(columns=True)
        self._visible_keys = [fact.key for fact in facts]
        if not facts:
            table.display = False
            empty.update("No facts in this session. Press n to add one.")
            empty.display = True
            return
        table.display = True
        empty.display = False
        table.add_columns("KEY", "VALUE", "UPDATED")
        for fact in facts:
            table.add_row(
                fact.key,
                _clip(fact.value),
                _short_time(fact.created),
                key=fact.key,
            )

    def _fill_search(self, query: str, results: Sequence[FactEntry]) -> None:
        table = self.query_one("#facts-table", widgets.MonoTable)
        empty = self.query_one("#facts-empty", Static)
        table.clear(columns=True)
        self._visible_keys = [fact.key for fact in results]
        if not results:
            table.display = False
            empty.update("No facts match %r." % query)
            empty.display = True
            return
        table.display = True
        empty.display = False
        table.add_columns("KEY", "VALUE", "SCORE")
        for fact in results:
            score = "%.3f" % fact.score if fact.score is not None else "\u2014"
            table.add_row(fact.key, _clip(fact.value), score, key=fact.key)

    def _fill_history(self, history: Sequence[FactEntry]) -> None:
        table = self.query_one("#history-table", widgets.MonoTable)
        empty = self.query_one("#history-empty", Static)
        table.clear(columns=True)
        if not history:
            table.display = False
            empty.update("No superseded facts.")
            empty.display = True
            return
        table.display = True
        empty.display = False
        table.add_columns("KEY", "PREVIOUS VALUE", "SUPERSEDED")
        for index, fact in enumerate(history):
            table.add_row(
                fact.key,
                _clip(fact.value),
                _short_time(fact.invalid_at),
                key="history-%d" % index,
            )

    def _render_overview(
        self, facts: Sequence[FactEntry], history: Sequence[FactEntry]
    ) -> None:
        latest = max((fact.created for fact in facts if fact.created), default="")
        lines = [
            "Session: %s" % (self.session_id or ""),
            "Active facts: %d" % len(facts),
            "Superseded versions: %d" % len(history),
            "Last active: %s" % (_short_time(latest) if latest else "\u2014"),
            "",
            "Press 2 for facts, 4 for history, 5 for settings.",
        ]
        self.query_one("#overview-body", Static).update("\n".join(lines))

    def _render_trace(self, trace: Optional[Dict[str, Any]]) -> None:
        body = self.query_one("#trace-body", Static)
        if not trace:
            body.update(
                "No gateway trace available.\n"
                "Start the gateway with `cyrrus serve`, then retry."
            )
            return
        lines = ["Last gateway requests:", ""]
        for request in trace.get("requests", [])[:8]:
            method = request.get("method", "?")
            path = request.get("path", "?")
            lines.append("%-6s %s" % (method, path))
            prompt = request.get("prompt")
            if prompt:
                lines.append("       prompt: %s" % _clip(prompt, 56))
        model = trace.get("model")
        if model:
            lines.extend(["", "Model: %s" % model])
        body.update("\n".join(lines))

    def _render_settings(self) -> None:
        self.query_one("#settings-body", Static).update(
            "memory.min_relative_score = %.2f\n\n"
            "Range: 0.0 to 1.0. Facts below this fraction of the best\n"
            "match score are dropped from retrieval.\n\n"
            "Press s to edit. Press esc to go back."
            % self._min_relative_score
        )

    # -- navigation -------------------------------------------------------
    def _focus_active(self) -> None:
        active = self.tabs.active
        if active == "tab-facts":
            self.query_one("#facts-table", widgets.MonoTable).focus()
        elif active == "tab-history":
            self.query_one("#history-table", widgets.MonoTable).focus()
        else:
            self.tabs.query_one(Tabs).focus()

    def _select_tab(self, tab_id: str) -> None:
        self.tabs.active = tab_id
        self._focus_active()

    def _typing(self) -> bool:
        return isinstance(self.app.focused, Input)

    def action_tab_1(self) -> None:
        if not self._typing():
            self._select_tab("tab-overview")

    def action_tab_2(self) -> None:
        if not self._typing():
            self._select_tab("tab-facts")

    def action_tab_3(self) -> None:
        if not self._typing():
            self._select_tab("tab-trace")

    def action_tab_4(self) -> None:
        if not self._typing():
            self._select_tab("tab-history")

    def action_tab_5(self) -> None:
        if not self._typing():
            self._select_tab("tab-settings")

    def action_back(self) -> None:
        if self._search_visible:
            self._hide_search()
            return
        self.app.show_home()

    def action_refresh(self) -> None:
        self.reload()

    # -- facts ------------------------------------------------------------
    def action_search(self) -> None:
        if not self.session_id or self.tabs.active != "tab-facts":
            self._select_tab("tab-facts")
        search = self.query_one("#facts-search", Input)
        self._search_visible = True
        search.display = True
        search.focus()

    def _hide_search(self) -> None:
        search = self.query_one("#facts-search", Input)
        self._search_visible = False
        search.value = ""
        search.display = False
        self.query_one("#facts-table", widgets.MonoTable).focus()
        self._fill_facts(self._facts)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "facts-search":
            return
        query = event.value.strip()
        if not query:
            self._fill_facts(self._facts)
            return
        self.run_worker(self._search(query), group="search", exclusive=True)

    async def _search(self, query: str) -> None:
        if not self.session_id:
            return
        try:
            results = await asyncio.to_thread(self.service.search, self.session_id, query)
        except Exception as exc:  # noqa: BLE001
            self.app.toast("Search failed: %s" % exc)
            return
        self._fill_search(query, results)

    def action_add_fact(self) -> None:
        if not self.session_id:
            return
        self.app.push_screen(
            widgets.FormDialog(
                "New fact",
                [("key", "Key", ""), ("value", "Value", "")],
                validate=_validate_new_fact,
                on_save=self._queue_add,
            )
        )

    def _queue_add(self, values: Dict[str, str]) -> None:
        session_id = self.session_id
        if not session_id:
            return
        key = values.get("key", "").strip()
        value = values.get("value", "").strip()
        self.run_worker(self._add(session_id, key, value), group="action", exclusive=False)

    async def _add(self, session_id: str, key: str, value: str) -> None:
        result = await asyncio.to_thread(self.service.add_fact, session_id, key, value)
        if not result.get("success"):
            self.app.toast("Could not add fact: %s" % result.get("error"))
            return
        self.app.toast("Fact added: %s" % key)
        await self._reload_facts()

    def action_forget_fact(self) -> None:
        table = self.query_one("#facts-table", widgets.MonoTable)
        if not table.display or table.row_count == 0:
            return
        index = table.cursor_row if table.cursor_row is not None else 0
        if index >= len(self._visible_keys):
            return
        key = self._visible_keys[index]
        self.app.push_screen(
            widgets.ConfirmDialog(
                "Forget fact %r?" % key,
                confirm_label="Forget",
                cancel_label="Keep",
            ),
            callback=lambda confirmed: self._forget_if(confirmed, key),
        )

    def _forget_if(self, confirmed: Optional[bool], key: str) -> None:
        if not confirmed or not self.session_id:
            return
        self.run_worker(
            self._forget(self.session_id, key), group="action", exclusive=False
        )

    async def _forget(self, session_id: str, key: str) -> None:
        result = await asyncio.to_thread(self.service.forget, session_id, key)
        if not result.get("success") or not result.get("deleted"):
            self.app.toast("Could not forget fact: %s" % (result.get("error") or key))
            return
        self.app.toast("Fact forgotten: %s" % key)
        await self._reload_facts()

    def action_export(self) -> None:
        if not self.session_id:
            return
        self.run_worker(self._export(self.session_id), group="action", exclusive=False)

    async def _export(self, session_id: str) -> None:
        path = self.service.export_path(session_id)
        result = await asyncio.to_thread(self.service.export, session_id, path)
        if not result.get("success"):
            self.app.toast("Export failed: %s" % result.get("error"))
            return
        self.app.toast("Exported %d facts to %s" % (result.get("count", 0), path))

    async def _reload_facts(self) -> None:
        if not self.session_id:
            return
        try:
            facts = await asyncio.to_thread(self.service.facts, self.session_id)
        except Exception as exc:  # noqa: BLE001
            self.app.toast("Reload failed: %s" % exc)
            return
        self._facts = facts
        self._fill_facts(facts)
        self._render_overview(facts, [fact for fact in self._facts if fact.invalid_at])

    # -- settings ---------------------------------------------------------
    def action_edit_setting(self) -> None:
        self.app.push_screen(
            widgets.FormDialog(
                "memory.min_relative_score",
                [("value", "Value (0.0 to 1.0)", "%.2f" % self._min_relative_score)],
                validate=_validate_setting,
                on_save=self._queue_setting,
            )
        )

    def _queue_setting(self, values: Dict[str, str]) -> None:
        self.run_worker(
            self._save_setting(values.get("value", "")),
            group="action",
            exclusive=False,
        )

    async def _save_setting(self, raw_value: str) -> None:
        number, error = parse_min_relative_score(raw_value)
        if error or number is None:
            self.app.toast(error or "Invalid setting")
            return
        try:
            saved = await asyncio.to_thread(self.service.write_min_relative_score, number)
        except Exception as exc:  # noqa: BLE001
            self.app.toast("Could not save setting: %s" % exc)
            return
        self._min_relative_score = saved
        self._render_settings()
        self.app.toast("Saved memory.min_relative_score = %.2f" % saved)


def _validate_new_fact(values: Dict[str, str]) -> Optional[str]:
    key = values.get("key", "").strip()
    value = values.get("value", "").strip()
    if not key:
        return "Key cannot be empty."
    if len(key) > 256:
        return "Key is too long (max 256 characters)."
    if not value:
        return "Value cannot be empty."
    if len(value) > 2000:
        return "Value is too long (max 2000 characters)."
    return None


def _validate_setting(values: Dict[str, str]) -> Optional[str]:
    _number, error = parse_min_relative_score(values.get("value", ""))
    return error


class CyrrusApp(App):
    """Intro, Home, and the five-tab session view in one application."""

    CSS = theme.theme_css() + widgets.SCROLLBAR_CSS + """
    Screen {
        layout: vertical;
    }
    #header {
        height: 1;
        background: $surface;
        color: $foreground;
        padding: 0 1;
    }
    #views {
        height: 1fr;
    }
    HomeView {
        height: 1fr;
        padding: 1 2;
    }
    #home-summary {
        height: auto;
        padding: 0 0 1 0;
    }
    #sessions-panel {
        height: 1fr;
    }
    #sessions-table {
        height: 1fr;
    }
    .empty-state {
        height: auto;
        padding: 2 1;
        color: #808080;
        text-style: dim;
    }
    SessionView {
        height: 1fr;
        padding: 1 2;
    }
    #session-header {
        height: auto;
        padding: 0 0 1 0;
        text-style: bold;
    }
    #session-tabs {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
    }
    #facts-search {
        display: none;
        margin-bottom: 1;
    }
    #facts-table {
        height: 1fr;
    }
    #history-table {
        height: 1fr;
    }
    .panel-body {
        height: auto;
        padding: 1 1;
    }
    ToastStack {
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(
        self,
        *,
        demo: bool = False,
        db_path: Optional[Path] = None,
        config_path: Optional[Path] = None,
        show_intro: bool = True,
    ) -> None:
        super().__init__()
        self.demo = demo
        self._owned_dir: Optional[Path] = None
        db_path = Path(db_path) if db_path is not None else None
        config_path = Path(config_path) if config_path is not None else None

        if demo and db_path is None:
            self._owned_dir = Path(tempfile.mkdtemp(prefix="cyrrus-ui-demo-"))
            db_path = self._owned_dir / "memory.db"
        if demo and db_path is not None:
            db_path = build_demo_db(db_path)
            save_demo_trace(db_path)
        if config_path is None:
            config_path = (
                self._owned_dir / "cyrrus.config.json"
                if self._owned_dir is not None
                else get_project_config_path()
            )

        self.service = DataService(
            demo=demo,
            db_path=db_path,
            config_path=config_path,
            export_dir=self._owned_dir or Path.cwd(),
        )
        self.show_intro = show_intro

    def compose(self) -> ComposeResult:
        yield Static("cyrrus \u00b7 by Breezy Labs", id="header")
        with ContentSwitcher(initial="home-view", id="views"):
            yield HomeView(self.service, id="home-view")
            yield SessionView(self.service, id="session-view")
        yield widgets.ToastStack(id="toasts")

    def on_mount(self) -> None:
        self.register_theme(theme.build_theme("light"))
        self.theme = "cyrrus-light"
        home = self.query_one(HomeView)
        if self.show_intro:
            data = IntroData(
                sessions=0,
                facts=0,
                gateway="not configured",
                attention=0,
            )
            self.push_screen(IntroScreen(data), callback=lambda _result: home.focus_home())
        else:
            home.focus_home()

    def on_unmount(self) -> None:
        if self._owned_dir is not None:
            try:
                from ..sqlite_backend import close_backend

                if self.service.db_path:
                    close_backend(self.service.db_path)
            except Exception:  # noqa: BLE001
                pass
            shutil.rmtree(self._owned_dir, ignore_errors=True)

    # -- app-level actions ------------------------------------------------
    def action_quit(self) -> None:
        self.exit(0)

    def action_help(self) -> None:
        self.push_screen(widgets.HelpOverlay())

    def action_refresh(self) -> None:
        if self.query_one("#views", ContentSwitcher).current == "session-view":
            self.query_one(SessionView).reload()
        else:
            self.query_one(HomeView).reload()

    def open_session(self, session_id: str) -> None:
        self.query_one("#views", ContentSwitcher).current = "session-view"
        self.query_one(SessionView).open(session_id)

    def show_home(self) -> None:
        self.query_one("#views", ContentSwitcher).current = "home-view"
        self.query_one(HomeView).focus_home()

    def toast(self, message: str) -> None:
        try:
            self.query_one("#toasts", widgets.ToastStack).add_toast(message)
        except Exception:  # noqa: BLE001 - a toast must not break the app
            self.notify(message)


def _parse_argv(argv: Optional[Sequence[str]]) -> Dict[str, Any]:
    args = list(argv or [])
    options: Dict[str, Any] = {
        "demo": False,
        "db_path": None,
        "config_path": None,
        "show_intro": True,
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--demo":
            options["demo"] = True
            index += 1
        elif arg in ("--db", "--config") and index + 1 < len(args):
            key = "db_path" if arg == "--db" else "config_path"
            options[key] = Path(args[index + 1])
            index += 2
        elif arg == "--no-intro":
            options["show_intro"] = False
            index += 1
        else:
            index += 1
    return options


def run_ui(argv: Optional[Sequence[str]] = None) -> int:
    """Run the interactive UI; return the process exit code."""
    options = _parse_argv(argv)
    app = CyrrusApp(**options)
    result = app.run()
    return int(result or 0)


__all__ = [
    "CyrrusApp",
    "DataService",
    "HomeView",
    "SessionView",
    "parse_min_relative_score",
    "run_ui",
]


if __name__ == "__main__":
    raise SystemExit(run_ui())
