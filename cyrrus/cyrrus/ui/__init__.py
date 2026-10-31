"""User interface helpers for cyrrus.

This package is standard library only. It provides terminal capability
detection (:mod:`cyrrus.ui.caps`), a theme/palette layer
(:mod:`cyrrus.ui.theme`), terminal art (:mod:`cyrrus.ui.art`) and the
intro animation (:mod:`cyrrus.ui.anim`).

Nothing here imports third-party packages.
"""

from __future__ import annotations

from .caps import Caps, detect_caps
from .theme import (
    PALETTE,
    Glyphs,
    Theme,
    face,
    gradient_text,
    style,
    should_animate,
)

__all__ = [
    "Caps",
    "detect_caps",
    "PALETTE",
    "Glyphs",
    "Theme",
    "face",
    "gradient_text",
    "style",
    "should_animate",
]
