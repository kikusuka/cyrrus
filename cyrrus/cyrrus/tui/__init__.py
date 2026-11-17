"""Optional Textual user interface.

Importing :mod:`cyrrus.tui` is safe without the ``ui`` extra: Textual is
imported only when the interface is actually started.  The core package and
the existing CLI therefore stay standard-library only.
"""
from __future__ import annotations

from typing import Optional, Sequence


INSTALL_HINT = 'pip install "cyrrus[ui]"'


class UiUnavailable(RuntimeError):
    """Raised when the optional UI dependencies are not installed."""


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Start the interface (imports Textual lazily)."""
    args = list(argv or [])

    screen = None
    size = "80x24"
    index = 0
    while index < len(args):
        if args[index] == "--dump-frame" and index + 1 < len(args):
            screen = args[index + 1]
            index += 2
        elif args[index] == "--size" and index + 1 < len(args):
            size = args[index + 1]
            index += 2
        else:
            index += 1

    try:
        import textual  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised in a bare venv
        raise UiUnavailable(
            "The cyrrus UI requires the optional 'ui' extra. "
            "Install it with: " + INSTALL_HINT
        ) from exc

    if screen is not None:
        from .dump import main

        return main(screen, size)

    from .app import run_ui

    return run_ui(args)


__all__ = ["INSTALL_HINT", "UiUnavailable", "run"]
