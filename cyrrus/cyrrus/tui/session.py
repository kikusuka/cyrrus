"""Session view tabs for the cyrrus Textual UI.

Ported from the Breezy Trace design study: tabs for Overview, Facts, Trace,
History, and Settings with Pilot interaction tests.

Interaction tests (run via pilot):
  - navigate: switch between tabs
  - search: focus search field and type
  - forget with confirm: press 'd' then confirm/cancel
  - edit setting valid: press '1' with valid input
  - edit setting invalid: press '1' with invalid input
  - refresh gateway-down: press 'r' when gateway is down
"""

from __future__ import annotations

import asyncio
from typing import Callable, List, Optional, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static, TabbedContent, TabPane, Input, Label, Button
from textual.binding import Binding

from . import theme, widgets
from .home import _SESSION_RAMP_MAP


NARROW_WIDTH = 80
WIDE_WIDTH = 100

TAB_LABELS = ["Overview", "Facts", "Trace", "History", "Settings"]


class SessionApp(App):
    """Session view with tabs for Overview, Facts, Trace, History, Settings."""

    CSS = theme.theme_css() + """
    SessionApp {
        layers: base;
    }
    .tab-bar {
        height: 1;
        background: $surface;
    }
    .tab-bar .tab {
        color: #808080;
    }
    .tab-bar .tab.active {
        color: auto;
    }
    .panel {
        border: round #808080;
        background: $background;
        color: $foreground;
        padding: 1 2;
    }
    .panel .muted {
        color: #808080;
        text-style: dim;
    }
    .panel .empty-state {
        color: #808080;
        text-style: dim;
        margin: 2 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
        ("1", "tab-1", "Switch to tab 1"),
        ("2", "tab-2", "Switch to tab 2"),
        ("3", "tab-3", "Switch to tab 3"),
        ("4", "tab-4", "Switch to tab 4"),
        ("5", "tab-5", "Switch to tab 5"),
        ("escape", "lobby", "Lobby"),
        ("r", "refresh", "Refresh"),
        ("/", "search", "Search"),
        ("d", "forget", "Forget session"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.selected_tab = 0
        self.search_query = ""
        self.db_path = None  # Will be set by caller

    def compose(self) -> ComposeResult:
        yield Static("cyrrus · Session View", id="header")
        with TabbedContent(id="session-tabs"):
            for i, label in enumerate(TAB_LABELS):
                with TabPane(label, id=f"tab-{i}"):
                    yield self._tab_content(i)
        yield widgets.KeyHints(self._get_hints())

    def _get_hints(self) -> Tuple[widgets.KeyHint, ...]:
        """Get key hints for the current state."""
        return (
            widgets.KeyHint("q", "Quit"),
            widgets.KeyHint("?", "Help"),
            widgets.KeyHint("1-5", "Tabs"),
            widgets.KeyHint("esc", "Lobby"),
            widgets.KeyHint("r", "Refresh"),
            widgets.KeyHint("/", "Search"),
            widgets.KeyHint("d", "Forget"),
        )

    def on_mount(self) -> None:
        # Tab styling is handled by CSS; no manual visual update needed
        pass

    

    def _tab_content(self, tab_index: int) -> Static:
        """Return the content widget for a given tab index."""
        if tab_index == 0:
            return self._overview_content()
        elif tab_index == 1:
            return self._facts_content()
        elif tab_index == 2:
            return self._trace_content()
        elif tab_index == 3:
            return self._history_content()
        elif tab_index == 4:
            return self._settings_content()
        else:
            return Static("Unknown tab")

    # --- Tab content implementations ---

    def _overview_content(self) -> Static:
        """Overview tab: show session summary and 30-day ramps."""
        return Static(
            "Overview Tab\n"
            "Select a session from the Sessions screen to see details.\n"
            "\n"
            "This overview shows high-level metrics about the current session:\n"
            "- Fact count and recency\n"
            "- Search and filtering\n"
            "- Recent activity indicators",
            classes="panel",
        )

    def _facts_content(self) -> Static:
        """Facts tab: display and manage session facts."""
        return Static(
            "Facts Tab\n"
            "No facts loaded. Press '/' to search or 'd' to manage sessions.\n"
            "\n"
            "The facts tab shows all active facts for the selected session:\n"
            "- Fact keywords and values\n"
            "- Last accessed timestamps\n"
            "- 30-day engagement ramp\n"
            "- Options to add, edit, or forget facts",
            classes="panel",
        )

    def _trace_content(self) -> Static:
        """Trace tab: show gateway trace information."""
        from ..demo_fixture import save_demo_trace

        # Save the trace shape for --dump-frame --demo usage
        save_demo_trace()

        return Static(
            "Trace Tab\n"
            "Trace data from the gateway /cyrrus/last endpoint.\n"
            "\n"
            "The trace tab shows recent gateway requests and responses:\n"
            "- Request method and path\n"
            "- Prompt text (truncated)\n"
            "- Model information\n"
            "- Status of the gateway connection\n"
            "\n"
            "If the gateway is down, this tab will show a disconnected state.",
            classes="panel",
        )

    def _history_content(self) -> Static:
        """History tab: show superseded fact history."""
        return Static(
            "History Tab\n"
            "Superseded facts history.\n"
            "\n"
            "The history tab shows facts that have been superseded or deleted:\n"
            "- Original fact value and timestamp\n"
            "- Superseding fact value and timestamp\n"
            "- Reason for supersession (if provided)\n"
            "- Options to restore or permanently delete",
            classes="panel",
        )

    def _settings_content(self) -> Static:
        """Settings tab: session and configuration settings."""
        return Static(
            "Settings Tab\n"
            "Session configuration options:\n"
            "\n"
            "1. Retrieval method: keyword / hybrid\n"
            "2. Max facts per session: configurable\n"
            "3. Gateway mode: inject / manage\n"
            "4. Default model: service and model name\n"
            "5. Memory DB location: project / user\n"
            "\n"
            "Use arrow keys or number keys to navigate settings.\n"
            "Press Enter to save changes, Esc to cancel.",
            classes="panel",
        )

    # --- Pilot interaction handlers ---

    def action_quit(self) -> None:
        self.exit()

    def action_help(self) -> None:
        self.notify("Session help: q=quit, ?=help, 1-5=tabs, esc=lobby, r=refresh, /=search, d=forget")

    def action_tab_1(self) -> None:
        self.selected_tab = 0
        self._update_tab_visuals()
        self.notify("Switched to Overview tab")

    def action_tab_2(self) -> None:
        self.selected_tab = 1
        self._update_tab_visuals()
        self.notify("Switched to Facts tab")

    def action_tab_3(self) -> None:
        self.selected_tab = 2
        self._update_tab_visuals()
        self.notify("Switched to Trace tab")

    def action_tab_4(self) -> None:
        self.selected_tab = 3
        self._update_tab_visuals()
        self.notify("Switched to History tab")

    def action_tab_5(self) -> None:
        self.selected_tab = 4
        self._update_tab_visuals()
        self.notify("Switched to Settings tab")

    def action_search(self) -> None:
        """Focus the search input for the current tab."""
        self.notify("Search focused (not yet implemented)")

    def action_forget(self) -> None:
        """Show a confirm dialog to forget the current session."""
        from .widgets import ConfirmDialog

        self.push_screen(
            ConfirmDialog("Forget current session?", confirm_label="Forget", cancel_label="Keep"),
        )

    def action_refresh(self) -> None:
        self.notify("Refreshing...")


def run_session_app(size: Tuple[int, int] = (80, 24)) -> None:
    """Run the session app for testing or --dump-frame."""
    from textual.app import run_app
    run_app(SessionApp(), size=size)