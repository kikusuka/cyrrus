"""Tests for :mod:`cyrrus.ui.theme` — palette, style helpers, glyphs, faces."""

from __future__ import annotations

from cyrrus.ui.caps import Caps, COLOR_NONE, TRUECOLOR
from cyrrus.ui.theme import (
    BLUE,
    CYAN,
    Glyphs,
    Theme,
    face,
    gradient_text,
    should_animate,
    style,
)


def test_style_returns_plain_text_when_colour_is_none():
    caps = Caps(color_depth=COLOR_NONE, ansi=False)
    t = Theme(caps)
    assert t.style("hello") == "hello"
    assert t.status("ok", "ok") == "ok"


def test_style_uses_ansi_when_available():
    caps = Caps(is_tty=True, color_depth=TRUECOLOR, ansi=True, unicode=True)
    t = Theme(caps)
    out = t.status("ok", "ok")
    assert "\x1b[" in out
    assert out.endswith("\x1b[0m")
    assert "ok" in out


def test_gradient_text_is_plain_without_colour():
    caps = Caps(color_depth=COLOR_NONE, ansi=False)
    assert gradient_text("cyrrus", caps=caps) == "cyrrus"


def test_gradient_text_uses_ansi_when_available():
    caps = Caps(is_tty=True, color_depth=TRUECOLOR, ansi=True, unicode=True)
    out = gradient_text("cyrrus", caps=caps)
    assert "\x1b[38;2;" in out
    assert out.endswith("\x1b[0m")


def test_face_covers_all_states():
    caps = Caps(unicode=True, ansi=True)
    for state in ("idle", "thinking", "success", "error"):
        f = face(state, caps)
        assert isinstance(f, str) and f


def test_face_ascii_fallback_is_pure_ascii():
    caps = Caps(unicode=False, ansi=False)
    for state in ("idle", "thinking", "success", "error"):
        f = face(state, caps)
        assert all(ord(ch) < 128 for ch in f), f


def test_glyphs_ascii_fallback_is_pure_ascii():
    g = Glyphs.for_unicode(False)
    for attr in (
        "check", "cross", "warn", "arrow", "bullet",
        "corner_tl", "corner_tr", "corner_bl", "corner_br", "hline", "vline",
    ):
        val = getattr(g, attr)
        assert all(ord(ch) < 128 for ch in val), (attr, val)


def _mk(caps_overrides=None, config=None, mode="interactive"):
    base = dict(
        is_tty=True, color_depth="truecolor", unicode=True, width=100, height=40,
        ci=False, reduced_motion=False, ansi=True, term_dumb=False,
    )
    if caps_overrides:
        base.update(caps_overrides)
    return should_animate(Caps(**base), config or {"ui": {"animation": "auto"}}, mode)


def test_should_animate_true_table():
    assert _mk() is True


def test_should_animate_false_when_not_tty():
    assert _mk({"is_tty": False}) is False


def test_should_animate_false_in_ci():
    assert _mk({"ci": True}) is False


def test_should_animate_false_when_reduced_motion():
    assert _mk({"reduced_motion": True}) is False


def test_should_animate_false_when_term_dumb():
    assert _mk({"term_dumb": True}) is False


def test_should_animate_false_when_too_small():
    assert _mk({"width": 59, "height": 40}) is False
    assert _mk({"width": 100, "height": 17}) is False


def test_should_animate_false_when_animation_off():
    assert _mk(config={"ui": {"animation": "off"}}) is False


def test_should_animate_false_for_protocol_mode():
    assert _mk(mode="protocol") is False


def test_should_animate_false_for_noninteractive_mode():
    assert _mk(mode="noninteractive") is False
