"""Swap-in logo for the intro.

The final artwork is not decided yet; these are clean block letters spelling
CYRRUS.  Replace :data:`LOGO` with any list of equally wide strings.
"""
from __future__ import annotations

_LETTERS = {
    "C": [" \u2588\u2588\u2588\u2588", "\u2588    ", "\u2588    ", "\u2588    ", " \u2588\u2588\u2588\u2588"],
    "Y": ["\u2588   \u2588", " \u2588 \u2588 ", "  \u2588  ", "  \u2588  ", "  \u2588  "],
    "R": ["\u2588\u2588\u2588\u2588 ", "\u2588   \u2588", "\u2588\u2588\u2588\u2588 ", "\u2588  \u2588 ", "\u2588   \u2588"],
    "U": ["\u2588   \u2588", "\u2588   \u2588", "\u2588   \u2588", "\u2588   \u2588", " \u2588\u2588\u2588 "],
    "S": [" \u2588\u2588\u2588\u2588", "\u2588    ", " \u2588\u2588\u2588 ", "    \u2588", "\u2588\u2588\u2588\u2588 "],
}

LOGO = [
    " ".join(_LETTERS[letter][row] for letter in "CYRRUS")
    for row in range(5)
]
LOGO_WIDTH = len(LOGO[0]) if LOGO else 0
