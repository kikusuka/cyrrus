"""Intro animation: 40 ms ticks, kicker, logo scan, path, status lines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from . import logo
from .theme import glyphs


TICK_SECONDS = 0.04
MAX_TICKS = 90
KICKER = "C Y R R U S"
NODES = ("sources", "retrieve", "score", "pack", "model")
PATH_TICKS = 18


@dataclass
class IntroData:
    sessions: int = 0
    facts: int = 0
    gateway: str = "not configured"
    attention: int = 0
    ready_tick: int = 32


def end_tick(ready_tick: Optional[int] = None) -> int:
    """max(ready tick, 32) + 14, capped at 90 (the brief's formula)."""
    ready = 32 if ready_tick is None else max(0, int(ready_tick))
    return min(MAX_TICKS, max(ready, 32) + 14)


class IntroState:
    """Pure tick model; the screen only paints its lines."""

    def __init__(self, data: Optional[IntroData] = None, width: int = 80, height: Optional[int] = None) -> None:
        self.data = data or IntroData()
        self.width = max(20, int(width))
        self.height = height
        self.tick = 0
        self.finished = False
        self.end = end_tick(self.data.ready_tick)

    # -- animation ---------------------------------------------------------
    def advance(self, ticks: int = 1) -> None:
        self.tick = min(MAX_TICKS, self.tick + max(0, int(ticks)))
        if self.tick >= self.end:
            self.finished = True

    def skip(self) -> None:
        self.tick = self.end
        self.finished = True

    @property
    def phase(self) -> str:
        if self.tick >= self.end - 1:
            return "done"
        if self.tick < 6:
            return "kicker"
        if self.tick < 14:
            return "logo"
        if self.tick < 20:
            return "path"
        if self.tick < 26:
            return "registry"
        if self.tick < 32:
            return "gateway"
        return "attention"

    # -- pieces ------------------------------------------------------------
    def kicker_text(self) -> str:
        if self.tick < 6:
            return KICKER[: min(len(KICKER), (self.tick + 1) * 2)].rstrip()
        return KICKER

    def logo_scan(self) -> int:
        if self.tick < 6:
            return 0
        return min(logo.LOGO_WIDTH, (self.tick - 6) * 2)

    def logo_lines(self) -> List[str]:
        scan = self.logo_scan()
        if scan <= 0:
            return []
        if scan >= logo.LOGO_WIDTH:
            return list(logo.LOGO)
        lines = []
        for row in logo.LOGO:
            visible = list(row[:scan].ljust(logo.LOGO_WIDTH))
            for index in range(max(0, scan - 5), scan):
                if visible[index] == "\u2588":
                    visible[index] = "\u2592"
            lines.append("".join(visible))
        return lines

    def path_line(self) -> str:
        length = max(10, min(self.width - 2, 72))
        cells = [" "] * length
        for index in range(len(NODES)):
            cells[round(index * (length - 1) / (len(NODES) - 1))] = "\u25cf"
        for index in range(1, length - 1):
            if cells[index] == " ":
                cells[index] = "\u2500"
        progress = max(0, min(PATH_TICKS, self.tick - 14))
        if self.phase in ("kicker", "logo"):
            return ""
        revealed = max(1, int(length * progress / PATH_TICKS))
        shown = "".join(cells[:revealed])
        if progress < PATH_TICKS:
            shown = shown.rstrip("\u2500")
        return shown

    def status_rows(self) -> List[str]:
        check = glyphs().check
        rows: List[str] = []
        if self.tick >= 20:
            rows.append(
                "%s registry   %d sessions \u00b7 %d facts"
                % (check, self.data.sessions, self.data.facts)
            )
        if self.tick >= 26:
            ready = str(self.data.gateway).lower() == "ready"
            rows.append(
                "%s gateway    %s" % (check if ready else "!", self.data.gateway)
            )
        if self.tick >= 32 and self.data.attention > 0:
            rows.append("! attention  %d need attention" % self.data.attention)
        return rows

    # -- output ------------------------------------------------------------
    def render_lines(self, width: Optional[int] = None, height: Optional[int] = None) -> List[str]:
        width = self.width if width is None else max(10, int(width))
        rows: List[str] = []
        if self.tick < 6:
            rows.append(self.kicker_text().center(width))
            rows.extend([""] * 4)
            rows.append("")
            rows.append(" " * width)
            rows.append("")
        else:
            rows.append(self.kicker_text().center(width))
            rows.extend(line.center(width) for line in self.logo_lines())
            rows.append(" " * width)
            if self.tick >= 14:
                rows.append(self.path_line().center(width))
                if self.tick >= 20:
                    rows.append("  ".join(NODES).center(width))
                rows.append(" " * width)
            rows.extend(row.center(width) for row in self.status_rows())
            if self.tick >= 32:
                rows.append(" " * width)
            if not self.finished:
                rows.append("any key to skip".center(width))
        if height is None:
            height = self.height
        if height is not None:
            height = max(0, int(height))
            if len(rows) < height:
                top = (height - len(rows)) // 2
                bottom = height - len(rows) - top
                rows = [""] * top + rows + [""] * bottom
            else:
                rows = rows[:height]
        return [row[:width].ljust(width) for row in rows]


from textual.app import ComposeResult  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import Static  # noqa: E402


class IntroScreen(ModalScreen):
    """Paint the pure tick model; any key exits immediately."""

    DEFAULT_CSS = """
    IntroScreen { background: $background; color: $foreground; }
    IntroScreen #intro-body { width: 100%; height: 100%; }
    """

    def __init__(self, data: Optional[IntroData] = None) -> None:
        super().__init__()
        self.state = IntroState(data or IntroData())
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Static("", id="intro-body")

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK_SECONDS, self._tick)
        self._paint()

    def on_resize(self) -> None:
        self._paint()

    def _paint(self) -> None:
        width = max(20, self.app.size.width)
        height = max(8, self.app.size.height)
        self.query_one("#intro-body", Static).update(
            "\n".join(self.state.render_lines(width, height))
        )

    def _tick(self) -> None:
        self.state.advance(1)
        self._paint()
        if self.state.finished:
            self._finish()

    def on_key(self, event) -> None:
        event.stop()
        self.state.skip()
        self._paint()
        self._finish()

    def _finish(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.dismiss(None)
