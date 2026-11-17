"""Headless screen renderer for ``cyrrus ui --dump-frame``.

Uses the compositor path of the frame harness: no pyte, no terminal, no
database.  The same fixed demo data feeds the golden frames, so a packaged
binary can print the exact cells a test expects.
"""
from __future__ import annotations

import sys
from typing import List, Tuple

SCREENS: Tuple[str, ...] = ("gallery", "toast", "confirm", "form", "help")


def render_frame(screen: str, size: str = "80x24") -> str:
    """Return a width x height frame with a trailing newline."""
    from .goldens import GalleryApp
    from .harness import normalise_frame, parse_size, render_screen

    if screen not in SCREENS:
        raise KeyError(screen)
    width, height = parse_size(size)
    text = render_screen(GalleryApp(screen), (width, height))
    return normalise_frame(text, width)


def main(screen: str, size: str = "80x24") -> int:
    try:
        frame = render_frame(screen, size)
    except KeyError:
        print(
            "unknown screen '%s'; choose from: %s" % (screen, ", ".join(SCREENS)),
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print("invalid --size: %s" % exc, file=sys.stderr)
        return 2
    sys.stdout.write(frame)
    sys.stdout.flush()
    return 0


__all__: List[str] = ["SCREENS", "render_frame", "main"]
