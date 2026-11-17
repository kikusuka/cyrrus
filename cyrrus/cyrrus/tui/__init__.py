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
    try:
        import textual  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised in a bare venv
        raise UiUnavailable(
            "The cyrrus UI requires the optional 'ui' extra. "
            "Install it with: " + INSTALL_HINT
        ) from exc

    from .app import run_ui

    return run_ui(list(argv or []))


__all__ = ["INSTALL_HINT", "UiUnavailable", "run"]
