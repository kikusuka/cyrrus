"""Terminal capability detection.

The :class:`Caps` object is a plain data holder so it is trivial to fake in
unit tests (construct one by hand, no mocking required). All detection logic
lives in :func:`detect_caps` and uses only the standard library.

On Windows, ANSI/VT processing is enabled on stdout where possible so that
colour escape sequences actually render in Windows Terminal / modern conhost.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Caps:
    """Detected terminal capabilities.

    Attributes:
        is_tty: stdout is a terminal.
        color_depth: "truecolor" | "256" | "16" | "none".
        unicode: stdout encoding can represent common box-drawing/braille.
        width: terminal width in columns (fallback 80).
        height: terminal height in rows (fallback 24).
        ci: running under a CI provider (CI/GITHUB_ACTIONS set).
        reduced_motion: user requested reduced motion (CYRRUS_NO_ANIM).
        ansi: ANSI escape sequences are expected to work.
        term_dumb: TERM == "dumb".
    """

    is_tty: bool = False
    color_depth: str = "none"
    unicode: bool = False
    width: int = 80
    height: int = 24
    ci: bool = False
    reduced_motion: bool = False
    ansi: bool = False
    term_dumb: bool = False


# Colour-depth names (kept as module constants so tests can reference them).
TRUECOLOR = "truecolor"
COLOR_256 = "256"
COLOR_16 = "16"
COLOR_NONE = "none"


def _env(name: str) -> Optional[str]:
    """Return an environment value, or None when missing/empty."""
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _windows_ansi_enabled() -> bool:
    """Try to enable VT processing on stdout (Windows). Never raises."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        STDOUT = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STDOUT)
        if handle == 0 or handle == -1:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if new_mode == mode.value:
            return True  # already enabled
        return bool(kernel32.SetConsoleMode(handle, new_mode))
    except Exception:  # pragma: no cover - defensive
        return False


def _colour_depth() -> str:
    """Infer colour depth from NO_COLOR, TERM and COLORTERM."""
    if _env("NO_COLOR") is not None:
        return COLOR_NONE
    term = _env("TERM") or ""
    if term == "dumb":
        return COLOR_NONE
    colorterm = _env("COLORTERM") or ""
    if colorterm.lower() in {"truecolor", "24bit"}:
        return TRUECOLOR
    if "256color" in term.lower() or "256" in colorterm.lower():
        return COLOR_256
    # Common modern terminals (Windows Terminal, mintty, iTerm, etc.) support
    # at least 16-colour ANSI when not dumb/no-color.
    return COLOR_16


def _unicode_supported() -> bool:
    """Best-effort check that stdout can emit common Unicode glyphs."""
    try:
        encoding = (sys.stdout.encoding or "").lower()
    except Exception:  # pragma: no cover - stdout may be replaced
        return False
    if not encoding:
        return False
    for codec in ("utf-8", "utf8"):
        if encoding.startswith(codec):
            return True
    # Some Windows terminals declare cp1252 but still render Unicode; be
    # conservative and only claim Unicode for UTF-8 family encodings.
    return False


def detect_caps() -> Caps:
    """Detect the capabilities of the current terminal."""
    is_tty = False
    try:
        is_tty = sys.stdout.isatty()
    except Exception:  # pragma: no cover - defensive
        is_tty = False

    width, height = 80, 24
    try:
        size = shutil.get_terminal_size(fallback=(80, 24))
        width, height = int(size.columns), int(size.lines)
    except Exception:  # pragma: no cover - defensive
        width, height = 80, 24

    ci = (
        _env("CI") is not None
        or _env("GITHUB_ACTIONS") is not None
        or _env("GITLAB_CI") is not None
    )
    reduced_motion = _env("CYRRUS_NO_ANIM") is not None
    term = _env("TERM") or ""
    term_dumb = term == "dumb"

    color_depth = _colour_depth()
    unicode_supported = _unicode_supported()

    # ANSI works when we are on a TTY, not dumb, not no-color, and (on
    # Windows) VT processing could be enabled.
    ansi = is_tty and not term_dumb and color_depth != COLOR_NONE
    if sys.platform == "win32" and is_tty:
        _windows_ansi_enabled()

    return Caps(
        is_tty=is_tty,
        color_depth=color_depth,
        unicode=unicode_supported,
        width=width,
        height=height,
        ci=ci,
        reduced_motion=reduced_motion,
        ansi=ansi,
        term_dumb=term_dumb,
    )
