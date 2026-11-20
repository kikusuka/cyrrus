"""Gateway status panel for the cyrrus Textual UI.

Displays gateway status and last request summary only.
Ported from the Breezy Trace design study.
"""

from __future__ import annotations

from typing import Optional, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from . import theme


class GatewayPanel(Static):
    """A small panel showing gateway status and last request summary."""

    DEFAULT_CSS = """
    GatewayPanel {
        border: round #808080;
        background: $background;
        color: $foreground;
        padding: 1 2;
        width: 100%;
    }
    GatewayPanel .muted {
        color: #808080;
        text-style: dim;
    }
    """

    def __init__(self, gateway_mode: str = "inject", model: str = "none", **kwargs) -> None:
        super().__init__("", **kwargs)
        self.gateway_mode = gateway_mode
        self.model = model
        self._last_request: Optional[dict] = None

    def set_last_request(self, request: dict) -> None:
        """Set the last request summary from the gateway."""
        self._last_request = request
        self.refresh()

    def clear_last_request(self) -> None:
        """Clear the last request summary."""
        self._last_request = None
        self.refresh()

    def render(self) -> Text:
        text = Text()
        # Gateway status line
        mode_status = "online" if self.gateway_mode != "none" else "offline"
        # Use bold for online, dim for offline
        if mode_status == "online":
            text.append(f"Gateway: {mode_status}  ", style="bold")
        else:
            text.append(f"Gateway: {mode_status}  ", style="dim")
        text.append(f"Mode: {self.gateway_mode}", style="dim")

        # Model info
        text.append(f"  |  Model: {self.model}", style="dim")

        # Last request summary
        if self._last_request:
            text.append("  |  Last request:", style="bold")
            method = self._last_request.get("method", "?")
            path = self._last_request.get("path", "?")
            text.append(f"  {method} {path}", style="dim")
        else:
            text.append("  |  No requests yet", style="dim")

        return text