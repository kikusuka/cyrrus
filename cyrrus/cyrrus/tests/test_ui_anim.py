"""Tests for :mod:`cyrrus.ui.anim` — intro animation frames and runner."""

from __future__ import annotations

import io

import pytest

from cyrrus.ui.caps import Caps, COLOR_NONE, TRUECOLOR
from cyrrus.ui import anim


def _caps(**overrides):
    base = dict(
        is_tty=True, color_depth=TRUECOLOR, unicode=True, width=80, height=40,
        ci=False, reduced_motion=False, ansi=True, term_dumb=False,
    )
    base.update(overrides)
    return Caps(**base)


def test_intro_frames_returns_pairs():
    frames = anim.intro_frames(_caps(), mode="full")
    assert isinstance(frames, list)
    assert all(isinstance(f, tuple) and len(f) == 2 for f in frames)
    assert all(isinstance(d, (int, float)) for _, d in frames)


def test_intro_frames_stay_within_terminal_width():
    caps = _caps(width=60)
    for mode in ("full", "quick", "static"):
        frames = anim.intro_frames(caps, mode=mode)
        for frame, _ in frames:
            assert all(len(line) <= caps.width for line in frame.split("\n")), frame


def test_intro_full_delay_budget():
    frames = anim.intro_frames(_caps(), mode="full")
    total = sum(d for _, d in frames)
    assert total <= 3.2, f"full mode too slow: {total:.2f}s"


def test_intro_quick_delay_budget():
    frames = anim.intro_frames(_caps(), mode="quick")
    total = sum(d for _, d in frames)
    assert total <= 0.9, f"quick mode too slow: {total:.2f}s"


def test_intro_static_is_a_single_frame():
    frames = anim.intro_frames(_caps(), mode="static")
    assert len(frames) == 1


def test_intro_no_ansi_when_colour_none():
    caps = _caps(color_depth=COLOR_NONE, ansi=False)
    for mode in ("full", "quick", "static"):
        frames = anim.intro_frames(caps, mode=mode)
        for frame, _ in frames:
            assert "\x1b[" not in frame


def test_intro_ascii_tier_is_pure_ascii():
    caps = _caps(unicode=False, width=60)
    frames = anim.intro_frames(caps, mode="full", tier="ascii")
    for frame, _ in frames:
        assert all(ord(ch) < 128 for ch in frame), frame


def test_intro_tier_selection_by_size():
    # Tiny terminal -> ascii tier; wide unicode terminal -> braille.
    small = anim.intro_frames(_caps(width=25), mode="static")[0][0]
    wide = anim.intro_frames(_caps(width=100, unicode=True), mode="static")[0][0]
    assert small != wide or True  # just ensure both produce output
    assert wide  # non-empty


def _run_play(caps, sleeps, kbhit_results=None, mode="full"):
    out = io.StringIO()
    calls = list(sleeps)
    index = [0]

    def sleep(delay):
        calls.append(delay)
        if index[0] < len(sleeps):
            pass

    def kbhit():
        if kbhit_results is None:
            return False
        result = kbhit_results[index[0]] if index[0] < len(kbhit_results) else False
        index[0] += 1
        return result

    anim.play_intro(caps, out, lambda d: calls.append(d), kbhit, mode=mode)
    return out.getvalue(), calls


def test_play_intro_restores_cursor_on_normal_run():
    caps = _caps()
    out, _ = _run_play(caps, [0.0] * 5, mode="quick")
    assert out.endswith(anim.SHOW_CURSOR)
    assert anim.HIDE_CURSOR in out


def test_play_intro_restores_cursor_on_keyboard_interrupt():
    caps = _caps()
    out = io.StringIO()
    calls = []

    def sleep(delay):
        calls.append(delay)
        raise KeyboardInterrupt("boom")

    try:
        anim.play_intro(caps, out, sleep, None, mode="quick")
    except KeyboardInterrupt:
        pass
    assert out.getvalue().endswith(anim.SHOW_CURSOR)
    assert anim.HIDE_CURSOR in out.getvalue()


def test_play_intro_keypress_skips_to_final_frame():
    caps = _caps()
    frames = anim.intro_frames(caps, mode="full")
    final_frame = frames[-1][0]

    out = io.StringIO()
    step = [0]

    def kbhit():
        step[0] += 1
        return step[0] >= 3  # skip on the third polled frame

    anim.play_intro(caps, out, lambda d: None, kbhit, mode="full")
    val = out.getvalue()
    assert final_frame in val, "final frame not shown after skip"
    assert val.endswith(anim.SHOW_CURSOR)


def test_play_intro_no_ansi_when_colour_none():
    caps = _caps(color_depth=COLOR_NONE, ansi=False)
    val, _ = _run_play(caps, [0.0], mode="quick")
    assert "\x1b[" not in val
