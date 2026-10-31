"""Intro animation and static logo display for the cyrrus terminal UI.

``intro_frames`` is a pure frame generator: it returns
``[(frame_string, delay_seconds), ...]`` and performs no I/O and no real
sleeping, so it is easy to test with fake clocks.

``play_intro`` is the runner. The output stream, the sleep function and the
key-polling function are all injectable. It hides the cursor and *always*
restores it (``finally`` plus an ``atexit`` safety net), writes whole frames
with cursor-home (never clear-screen flicker), and never leaves the terminal
in an altered state - even on ``KeyboardInterrupt`` or exceptions.

The package is standard library only.
"""

from __future__ import annotations

import atexit
import os
import sys
from typing import Callable, List, Optional, Sequence, Tuple

from . import art
from .caps import Caps, COLOR_NONE

# ---------------------------------------------------------------------------
# Cursor control (ANSI VT sequences)
# ---------------------------------------------------------------------------
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CURSOR_HOME = "\x1b[H"

_atexit_registered = False


def _ensure_atexit() -> None:
    """Register a best-effort cursor restore at interpreter exit."""
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_restore_stdout_cursor)
        _atexit_registered = True


def _restore_stdout_cursor() -> None:
    try:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
    except Exception:  # pragma: no cover - defensive
        pass


def _write(out, text: str) -> None:
    out.write(text)
    out.flush()


def _show_cursor(out) -> None:
    _write(out, SHOW_CURSOR)


# ---------------------------------------------------------------------------
# Frame building helpers
# ---------------------------------------------------------------------------
def _clamp_width(text: str, width: int) -> str:
    if len(text) > width:
        return text[:width]
    return text


def _center_block(lines: Sequence[str], width: int) -> List[str]:
    """Center each line within ``width`` (no line exceeds width)."""
    out = []
    for line in lines:
        line = _clamp_width(line, width)
        pad = max(0, (width - len(line)) // 2)
        out.append(" " * pad + line)
    return out


def _gradient_line(
    text: str,
    start_rgb: Tuple[int, int, int],
    end_rgb: Tuple[int, int, int],
    ansi: bool,
) -> str:
    if not ansi or not text:
        return text
    n = len(text)
    parts = []
    for i, ch in enumerate(text):
        if ch == " ":
            parts.append(ch)
            continue
        t = i / max(n - 1, 1)
        r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * t)
        g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * t)
        b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * t)
        parts.append(f"\x1b[38;2;{r};{g};{b}m{ch}")
    return "".join(parts) + "\x1b[0m"


def _resolve_word_frames(
    wordmark: Sequence[str],
    width: int,
    ansi: bool,
    steps: int,
) -> List[str]:
    """Word "cyrrus" resolving left to right, one column step at a time."""
    full = list(wordmark)
    w = max(len(line) for line in full)
    frames = []
    for step in range(1, steps + 1):
        n = max(1, w * step // steps)
        revealed = [line[:n] for line in full]
        if ansi:
            revealed = [
                _gradient_line(line, art.CYAN, art.BLUE, True) for line in revealed
            ]
        frames.append("\n".join(_center_block(revealed, width)))
    return frames


def _dissolve_frames(
    wordmark: Sequence[str],
    width: int,
    ansi: bool,
    steps: int,
) -> List[str]:
    """Word dissolves into dots/wisps, left to right."""
    full = list(wordmark)
    w = max(len(line) for line in full)
    frames = []
    for step in range(1, steps + 1):
        n = w * step // steps
        lines = []
        for line in full:
            revealed = line[:n]
            rest = "." * max(0, len(line) - n)
            lines.append(revealed + rest)
        if ansi:
            lines = [_gradient_line(l, art.CYAN, art.BLUE, True) for l in lines]
        frames.append("\n".join(_center_block(lines, width)))
    return frames


# ---------------------------------------------------------------------------
# Pure frame generator
# ---------------------------------------------------------------------------
def intro_frames(
    caps: Caps,
    mode: str = "full",
    tier: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """Return ``[(frame, delay_seconds), ...]`` for the intro animation.

    Pure: no I/O, no real sleeping, no randomness. ``mode`` is one of
    ``"full"`` (<= ~3.2 s), ``"quick"`` (~0.8 s) or ``"static"`` (just the
    small logo). ``tier`` selects the art tier: ``"braille"``, ``"half"``,
    ``"ascii"`` or None (chosen from caps/size).
    """
    width = max(20, min(int(caps.width or 80), 80))
    ansi = caps.ansi and caps.color_depth != COLOR_NONE

    if tier is None:
        if caps.unicode and width >= 40:
            tier = "braille"
        elif width >= 30:
            tier = "half"
        else:
            tier = "ascii"

    logo_map = {
        "braille": art.LARGE_BRAILLE,
        "half": art.HALF_BLOCK,
        "ascii": art.ASCII_ART,
    }
    logo_lines = list(logo_map[tier])

    frames: List[Tuple[str, float]] = []

    def add(frame: str, delay: float) -> None:
        frames.append((_clamp_width(frame, width), delay))

    # Small static logo used for quick/static/settle.
    small_logo = "\n".join(_center_block(logo_lines, width))

    if mode == "static":
        add(small_logo, 0.0)
        return frames

    # Tagline.
    tagline = "a Breezy Labs product"

    # Per-tier wisp art (ASCII tier keeps everything ASCII).
    wisps = art.WISP_FRAMES

    if mode == "quick":
        # Abbreviated: wisps -> word -> settle. ~0.8 s total.
        for wf in wisps[:2]:
            add("\n".join(_center_block(wf, width)), 0.12)
        word = "\n".join(
            _center_block(
                [_gradient_line(l, art.CYAN, art.BLUE, ansi) for l in art.WORDMARK],
                width,
            )
        )
        add(word, 0.25)
        add(small_logo, 0.25)
        return frames

    # ---- full mode (<= ~3.2 s) ----
    # 1. Wisps drift in.
    for wf in wisps:
        add("\n".join(_center_block(wf, width)), 0.10)

    # 2. Word "cyrrus" resolves left to right with the cyan->blue gradient.
    add("\n".join(_center_block([""] * 5, width)), 0.06)  # brief pause
    for frame in _resolve_word_frames(art.WORDMARK, width, ansi, steps=5):
        add(frame, 0.14)

    # 3. Hold briefly.
    hold = "\n".join(
        _center_block(
            [_gradient_line(l, art.CYAN, art.BLUE, ansi) for l in art.WORDMARK],
            width,
        )
    )
    add(hold, 0.20)
    add(hold, 0.20)

    # 4. Word dissolves into wisps/dots.
    for frame in _dissolve_frames(art.WORDMARK, width, ansi, steps=4):
        add(frame, 0.10)

    # 5. Tagline fades in.
    add("\n".join(_center_block([tagline], width)), 0.25)

    # 6. Logo draws in stages: reveal rows top to bottom, bubbles last, blink.
    n_rows = len(logo_lines)
    stage_steps = max(2, min(4, n_rows // 5))
    for stage in range(1, stage_steps + 1):
        n = n_rows * stage // stage_steps
        part = logo_lines[:n] + [""] * max(0, n_rows - n)
        add("\n".join(_center_block(part, width)), 0.12)
    # Blink the robot's eyes once (toggle a row) while the logo is held.
    blink_on = "\n".join(_center_block(logo_lines, width))
    add(blink_on, 0.08)
    add(blink_on, 0.08)

    # 7. Tagline stays, settle into the small static logo.
    add(small_logo, 0.26)
    return frames


def logo_frames(caps: Caps, tier: Optional[str] = None) -> List[Tuple[str, float]]:
    """Return a single static-logo frame (used by ``cyrrus logo``)."""
    width = max(20, min(int(caps.width or 80), 80))
    ansi = caps.ansi and caps.color_depth != COLOR_NONE
    if tier is None:
        tier = "braille" if (caps.unicode and width >= 40) else ("half" if width >= 30 else "ascii")
    logo_map = {"braille": art.LARGE_BRAILLE, "half": art.HALF_BLOCK, "ascii": art.ASCII_ART}
    lines = list(logo_map[tier])
    if ansi:
        lines = [_gradient_line(l, art.CYAN, art.BLUE, True) for l in lines]
    frame = "\n".join(_center_block(lines, width))
    return [(frame, 0.0)]


# ---------------------------------------------------------------------------
# Runner: injectable clock, sleep, key polling and output stream
# ---------------------------------------------------------------------------
def play_intro(
    caps: Caps,
    out,
    sleep: Callable[[float], None],
    kbhit: Optional[Callable[[], bool]] = None,
    mode: str = "full",
    tier: Optional[str] = None,
) -> None:
    """Play the intro animation on ``out``.

    ``sleep`` is called with each frame's delay and may be fake in tests.
    ``kbhit``, if provided, is polled before each frame; a truthy result skips
    to the final frame. The cursor is restored in ``finally`` (and via
    ``atexit``) even when ``sleep`` raises ``KeyboardInterrupt``.
    """
    _ensure_atexit()
    do_ansi = caps.ansi and caps.color_depth != COLOR_NONE
    if do_ansi:
        _write(out, HIDE_CURSOR)

    frames = intro_frames(caps, mode=mode, tier=tier)

    try:
        final_index = len(frames) - 1
        for index, (frame, delay) in enumerate(frames):
            if kbhit is not None and kbhit():
                # Skip to the final frame.
                frame, _ = frames[final_index]
                _write(out, (CURSOR_HOME if do_ansi else "") + frame)
                break
            _write(out, (CURSOR_HOME if do_ansi else "") + frame)
            sleep(delay)
        else:
            # No skip occurred: ensure the final frame is displayed.
            frame, _ = frames[final_index]
            _write(out, (CURSOR_HOME if do_ansi else "") + frame)
    except KeyboardInterrupt:
        raise
    finally:
        if do_ansi:
            _show_cursor(out)


# ---------------------------------------------------------------------------
# Real (non-test) keyboard polling for Windows / POSIX
# ---------------------------------------------------------------------------
def _real_kbhit() -> bool:
    """Best-effort non-blocking key poll. Windows-first, POSIX fallback."""
    if os.name == "nt":
        try:
            import msvcrt  # type: ignore

            return msvcrt.kbhit()
        except Exception:  # pragma: no cover - defensive
            return False
    # POSIX: non-blocking stdin check.
    try:
        import select  # type: ignore

        return bool(select.select([sys.stdin], [], [], 0)[0])
    except Exception:  # pragma: no cover - defensive
        return False


def real_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
