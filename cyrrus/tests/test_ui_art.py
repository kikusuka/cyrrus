"""Tests for :mod:`cyrrus.ui.art` and the dev art generator.

The generated :mod:`cyrrus.ui.art` module is standard library only. The dev
tool (``devtools/make_terminal_art.py``) uses Pillow but is not packaged and is
never imported by the package.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from cyrrus.ui import art

ART_PATH = Path(art.__file__)


def test_art_imports_no_third_party():
    tree = ast.parse(ART_PATH.read_text(encoding="utf-8"))
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    # art.py is generated standard-library-only; only __future__ and typing appear.
    modules = set()
    for node in imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        else:
            if node.module:
                modules.add(node.module.split(".")[0])
    stdlib = {"__future__", "typing"}
    assert modules <= stdlib, modules


def test_art_is_not_larger_than_reasonable():
    size = ART_PATH.stat().st_size
    assert size < 256 * 1024, f"art.py too large: {size} bytes"


def test_tiers_fit_within_80x24():
    for name in ("LARGE_BRAILLE", "SMALL_BRAILLE", "HALF_BLOCK", "ASCII_ART", "WORDMARK"):
        lines = getattr(art, name)
        assert lines, f"{name} is empty"
        width = max(len(line) for line in lines)
        assert width <= 80, f"{name} too wide: {width}"
        assert len(lines) <= 24, f"{name} too tall: {len(lines)}"


def test_wordmark_has_five_rows():
    assert len(art.WORDMARK) == 5
    assert all(line.strip() for line in art.WORDMARK)


def test_dev_tool_regenerates_identical_art():
    """The generator is deterministic; skipping when Pillow is unavailable."""
    try:
        from devtools.make_terminal_art import build_art_module  # noqa: import-not-at-top
    except ImportError:  # Pillow or the tool is unavailable in this env
        pytest.skip("Pillow/dev tool not importable")
    first = build_art_module()
    second = build_art_module()
    assert first == second, "art generation is not deterministic"
    # The checked-in art.py matches a fresh generation.
    assert first == ART_PATH.read_text(encoding="utf-8")
