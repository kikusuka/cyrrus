"""Tests for :mod:`cyrrus.ui.caps` — terminal capability detection.

The :class:`Caps` object is a plain dataclass, so it is trivial to fake in
tests; no mocking is required.
"""

from __future__ import annotations

import os

import pytest

from cyrrus.ui.caps import (
    Caps,
    COLOR_16,
    COLOR_256,
    COLOR_NONE,
    TRUECOLOR,
    detect_caps,
)


def test_caps_dataclass_is_easy_to_fake():
    """Constructing a Caps by hand must work (no mocking needed)."""
    caps = Caps(
        is_tty=True,
        color_depth=TRUECOLOR,
        unicode=True,
        width=120,
        height=40,
        ci=False,
        reduced_motion=False,
        ansi=True,
        term_dumb=False,
    )
    assert caps.width == 120
    assert caps.height == 40
    assert caps.color_depth == TRUECOLOR
    assert caps.ansi is True


def test_detect_caps_returns_a_caps_object():
    caps = detect_caps()
    assert isinstance(caps, Caps)
    assert caps.color_depth in (COLOR_NONE, COLOR_16, COLOR_256, TRUECOLOR)
    assert isinstance(caps.width, int) and caps.width > 0
    assert isinstance(caps.height, int) and caps.height > 0
    assert isinstance(caps.ci, bool)
    assert isinstance(caps.reduced_motion, bool)
    assert isinstance(caps.ansi, bool)
    assert isinstance(caps.term_dumb, bool)


def test_colour_depth_no_color_wins(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("COLORTERM", raising=False)
    from cyrrus.ui import caps as caps_mod

    assert caps_mod._colour_depth() == COLOR_NONE


def test_colour_depth_dumb_term(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("COLORTERM", raising=False)
    from cyrrus.ui import caps as caps_mod

    assert caps_mod._colour_depth() == COLOR_NONE


def test_colour_depth_truecolor(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    from cyrrus.ui import caps as caps_mod

    assert caps_mod._colour_depth() == TRUECOLOR


def test_colour_depth_256(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.delenv("COLORTERM", raising=False)
    from cyrrus.ui import caps as caps_mod

    assert caps_mod._colour_depth() == COLOR_256


def test_reduced_motion_from_env(monkeypatch):
    monkeypatch.delenv("CYRRUS_NO_ANIM", raising=False)
    from cyrrus.ui import caps as caps_mod

    assert caps_mod._env("CYRRUS_NO_ANIM") is None
    monkeypatch.setenv("CYRRUS_NO_ANIM", "1")
    assert caps_mod._env("CYRRUS_NO_ANIM") == "1"
