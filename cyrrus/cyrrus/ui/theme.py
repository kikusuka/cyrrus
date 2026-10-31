"""Theme, palette and style helpers for the cyrrus terminal UI.

Colours are sampled from the cyrrus logo: a cyan top and a blue bottom.
Every public helper returns plain text when the terminal cannot render ANSI
or colour, so output is safe on any stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .caps import Caps, COLOR_16, COLOR_256, COLOR_NONE, TRUECOLOR

# --- Palette sampled from the logo -----------------------------------------
# Top of the logo gradient (cyan) and bottom (blue).
CYAN: Tuple[int, int, int] = (90, 200, 220)
BLUE: Tuple[int, int, int] = (60, 150, 210)

# Status / accent colours (soft, never neon).
GRAY: Tuple[int, int, int] = (140, 140, 150)
GREEN: Tuple[int, int, int] = (120, 200, 120)
AMBER: Tuple[int, int, int] = (230, 180, 80)
RED: Tuple[int, int, int] = (220, 90, 90)

PALETTE = {
    "cyan": CYAN,
    "blue": BLUE,
    "gray": GRAY,
    "green": GREEN,
    "amber": AMBER,
    "red": RED,
}

RESET = "\x1b[0m"
BOLD = "\x1b[1m"


def _ansi_fg(rgb: Tuple[int, int, int], color_depth: str) -> str:
    """ANSI foreground escape for an RGB colour, or empty string."""
    if color_depth == COLOR_NONE:
        return ""
    r, g, b = rgb
    if color_depth == TRUECOLOR:
        return f"\x1b[38;2;{r};{g};{b}m"
    if color_depth == COLOR_256:
        return f"\x1b[38;5;{_rgb256(r, g, b)}m"
    # 16 colour: pick nearest basic/bright ANSI.
    return f"\x1b[{_ansi16(r, g, b)}m"


def _rgb256(r: int, g: int, b: int) -> int:
    """Closest 216-colour cube index (16..231)."""
    r5 = (r * 5) // 256
    g5 = (g * 5) // 256
    b5 = (b * 5) // 256
    r5 = min(max(r5, 0), 5)
    g5 = min(max(g5, 0), 5)
    b5 = min(max(b5, 0), 5)
    return 16 + 36 * r5 + 6 * g5 + b5


def _ansi16(r: int, g: int, b: int) -> int:
    """Map an RGB colour to a 16-colour ANSI SGR code (30-37 or 90-97)."""
    # Distinguish bright vs dark by luminance.
    bright = (r * 299 + g * 587 + b * 114) > 400 * 255 // 2  # > ~127.5
    base = 90 if bright else 30
    if b > r and b > g:
        return base + 4  # blue
    if g > r and g > b:
        return base + 6  # cyan
    if r > g and r > b:
        return base + 1  # red
    if g > b:
        return base + 2  # green
    return base + 7  # white/gray


def _wrap(text: str, escape: str) -> str:
    if not escape:
        return text
    return f"{escape}{text}{RESET}"


@dataclass
class Glyphs:
    """Unicode glyphs with ASCII fallbacks.

    Construct with ``Glyphs(unicode=True)`` or ``Glyphs(unicode=False)``.
    """

    check: str
    cross: str
    warn: str
    arrow: str
    bullet: str
    # Box drawing.
    corner_tl: str
    corner_tr: str
    corner_bl: str
    corner_br: str
    hline: str
    vline: str

    @classmethod
    def for_unicode(cls, unicode_supported: bool) -> "Glyphs":
        if unicode_supported:
            return cls(
                check="✓",
                cross="✗",
                warn="⚠",
                arrow="→",
                bullet="•",
                corner_tl="╭",
                corner_tr="╮",
                corner_bl="╰",
                corner_br="╯",
                hline="─",
                vline="│",
            )
        return cls(
            check="OK",
            cross="X",
            warn="!",
            arrow="->",
            bullet="*",
            corner_tl="+",
            corner_tr="+",
            corner_bl="+",
            corner_br="+",
            hline="-",
            vline="|",
        )


class Theme:
    """Style helpers that degrade gracefully to plain text."""

    def __init__(self, caps: Optional[Caps] = None):
        self.caps = caps or Caps()
        self.glyphs = Glyphs.for_unicode(self.caps.unicode)

    def _enabled(self) -> bool:
        return self.caps.ansi and self.caps.color_depth != COLOR_NONE

    def style(
        self,
        text: str,
        fg: Optional[Tuple[int, int, int]] = None,
        bold: bool = False,
    ) -> str:
        """Return ``text`` wrapped in ANSI colour, or plain text."""
        if not self._enabled():
            return text
        parts = []
        if bold:
            parts.append(BOLD)
        if fg is not None:
            parts.append(_ansi_fg(fg, self.caps.color_depth))
        if not parts:
            return text
        return "".join(parts) + text + RESET

    def status(self, text: str, kind: str = "info") -> str:
        """Style a status word with a colour appropriate to ``kind``."""
        colour = {
            "ok": GREEN,
            "success": GREEN,
            "warn": AMBER,
            "warning": AMBER,
            "error": RED,
            "red": RED,
            "gray": GRAY,
        }.get(kind, CYAN)
        return self.style(text, fg=colour, bold=True)

    def gradient_text(
        self,
        text: str,
        start: Tuple[int, int, int] = CYAN,
        end: Tuple[int, int, int] = BLUE,
    ) -> str:
        """Return ``text`` coloured with a linear ``start``->``end`` gradient.

        Each character gets its own interpolated colour (truecolor / 256) or
        plain text when colour is unavailable.
        """
        if not self._enabled() or not text:
            return text
        depth = self.caps.color_depth
        n = len(text)
        out = []
        for i, ch in enumerate(text):
            t = i / max(n - 1, 1)
            r = int(start[0] + (end[0] - start[0]) * t)
            g = int(start[1] + (end[1] - start[1]) * t)
            b = int(start[2] + (end[2] - start[2]) * t)
            out.append(_wrap(ch, _ansi_fg((r, g, b), depth)))
        return "".join(out)


def face(state: str, caps: Optional[Caps] = None) -> str:
    """Robot face for a given state, with ASCII fallback.

    States: ``idle``, ``thinking``, ``success``, ``error``.
    """
    c = caps or Caps()
    unicode_ok = c.unicode
    ansi = c.ansi and c.color_depth != COLOR_NONE
    blue = _ansi_fg((60, 150, 210), c.color_depth) if ansi else ""
    cyan = _ansi_fg((90, 200, 220), c.color_depth) if ansi else ""
    reset = RESET if ansi else ""

    if unicode_ok:
        faces = {
            "idle": f"{blue}(o {cyan}o{blue}){reset}",
            "thinking": f"{blue}(..){reset}",
            "success": f"{blue}(^_^){reset}",
            "error": f"{blue}(x_x){reset}",
        }
    else:
        faces = {
            "idle": "(O O)",
            "thinking": "(..)",
            "success": "(^_^)",
            "error": "(x_x)",
        }
    return faces.get(state, faces["idle"])


def style(
    text: str,
    fg: Optional[Tuple[int, int, int]] = None,
    bold: bool = False,
    caps: Optional[Caps] = None,
) -> str:
    """Module-level convenience: style text with a default (or given) Caps."""
    return Theme(caps).style(text, fg=fg, bold=bold)


def gradient_text(
    text: str,
    start: Tuple[int, int, int] = CYAN,
    end: Tuple[int, int, int] = BLUE,
    caps: Optional[Caps] = None,
) -> str:
    """Module-level convenience: gradient-colour text with a default Caps."""
    return Theme(caps).gradient_text(text, start=start, end=end)


def should_animate(caps: Caps, config: dict, mode: str = "interactive") -> bool:
    """Decide whether an animation should play.

    Truth table (animated only when *all* of the following hold):

    * ``mode`` is ``"interactive"`` — any protocol/non-interactive mode
      (e.g. a future ``cyrrus mcp`` talking over stdout) is always ``False``.
    * stdout is a TTY.
    * not running under CI.
    * ``CYRRUS_NO_ANIM`` is not set.
    * ``TERM`` is not ``dumb``.
    * terminal is at least 60 columns by 18 rows.
    * ``config["ui"]["animation"]`` is not ``"off"``.

    Returns ``False`` otherwise.
    """
    if mode in ("protocol", "noninteractive"):
        return False
    if not caps.is_tty:
        return False
    if caps.ci:
        return False
    if caps.reduced_motion:
        return False
    if caps.term_dumb:
        return False
    if caps.width < 60 or caps.height < 18:
        return False
    ui = config.get("ui", {}) if isinstance(config, dict) else {}
    if ui.get("animation", "auto") == "off":
        return False
    return True
