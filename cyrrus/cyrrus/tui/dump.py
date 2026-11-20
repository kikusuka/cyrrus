"""Headless screen renderer for ``cyrrus ui --dump-frame``.

Uses the compositor path of the frame harness: no pyte, no terminal, and no
interactive session.  Gallery screens use fixed widgets; ``home`` and
``session`` render the runnable app against a demo or real database.
"""
from __future__ import annotations

import sys
from typing import List, Tuple

SCREENS: Tuple[str, ...] = (
    "gallery",
    "toast",
    "confirm",
    "form",
    "help",
    "home",
    "session",
)
APP_SCREENS: Tuple[str, ...] = ("home", "session")


def render_frame(screen: str, size: str = "80x24", demo: bool = False) -> str:
    """Return a width x height frame with a trailing newline."""
    from .harness import normalise_frame, parse_size, render_screen

    if screen not in SCREENS:
        raise KeyError(screen)
    width, height = parse_size(size)
    if screen in APP_SCREENS:
        from .app import CyrrusApp

        app = CyrrusApp(demo=demo, show_intro=False)
        keys = () if screen == "home" else ("enter",)
        text = render_screen(app, (width, height), keys=keys)
    else:
        from .goldens import GalleryApp

        text = render_screen(GalleryApp(screen), (width, height))
    return normalise_frame(text, width)


def main(screen: str, size: str = "80x24", demo: bool = False) -> int:
    try:
        frame = render_frame(screen, size, demo=demo)
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


__all__: List[str] = ["SCREENS", "APP_SCREENS", "render_frame", "main"]
