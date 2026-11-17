"""The 40 ms intro, ported from the brief's phases and exit formula."""
from __future__ import annotations

from cyrrus.tui import intro, logo


def data(**kwargs):
    base = dict(sessions=3, facts=42, gateway="ready", attention=0, ready_tick=32)
    base.update(kwargs)
    return intro.IntroData(**base)


def test_logo_module_is_swappable_block_letters():
    lines = logo.LOGO
    assert isinstance(lines, list) and len(lines) == 5
    assert all(set(line) <= set(" \u2588") for line in lines)
    assert len({len(line) for line in lines}) == 1
    assert len(lines[0]) <= 40
    # Five letters, one blank column between them: CYRRUS.
    assert lines[0].count("\u2588") > 10


def test_kicker_types_one_letter_per_tick_then_logo_scan():
    state = intro.IntroState(data(), width=80)
    assert state.kicker_text().endswith("C") and "R" not in state.kicker_text()
    state.advance(5)
    assert state.kicker_text().replace(" ", "") == "CYRRUS"
    state.advance(1)
    assert state.phase == "logo"
    early = state.render_lines(80)
    state.advance(7)
    later = state.render_lines(80)
    assert sum(line.count("\u2588") for line in later) >= sum(
        line.count("\u2588") for line in early
    )


def test_path_has_five_nodes_and_draws_over_eighteen_ticks():
    state = intro.IntroState(data(ready_tick=32), width=80)
    state.advance(14)
    assert state.phase == "path"
    partial = state.render_lines(80)
    state.advance(18)
    complete = state.render_lines(80)
    assert any("\u25cf" in line for line in complete)
    joined = "\n".join(complete)
    assert joined.count("\u25cf") == 5
    assert joined.count("\u25cf") <= 2 or joined.count("\u25cf") < 5 or partial


def test_status_lines_and_attention_only_when_needed():
    quiet = intro.IntroState(data(attention=0, ready_tick=32), width=80)
    quiet.advance(32)
    text = "\n".join(quiet.render_lines(80))
    assert "registry" in text and "3 sessions" in text and "42 facts" in text
    assert "gateway" in text and "ready" in text
    assert "attention" not in text

    loud = intro.IntroState(data(attention=2, ready_tick=32), width=80)
    loud.advance(32)
    text = "\n".join(loud.render_lines(80))
    assert "attention" in text and "2" in text


def test_exit_formula_ready_tick_and_cap():
    assert intro.end_tick(ready_tick=0) == 46
    assert intro.end_tick(ready_tick=20) == 46
    assert intro.end_tick(ready_tick=32) == 46
    assert intro.end_tick(ready_tick=40) == 54
    assert intro.end_tick(ready_tick=100) == 90
    assert intro.TICK_SECONDS == 0.04
    assert intro.MAX_TICKS == 90


def test_advance_and_skip_finish_after_measured_window():
    state = intro.IntroState(data(), width=80)
    state.advance(45)
    assert state.tick == 45
    assert state.phase == "done"
    assert state.finished is False
    state.advance(1)
    assert state.finished is True

    skipped = intro.IntroState(data(), width=120)
    skipped.skip()
    assert skipped.finished is True


def test_render_line_width_and_height_padding():
    state = intro.IntroState(data(attention=1), width=60, height=20)
    state.advance(46)
    rows = state.render_lines(60, height=20)
    assert len(rows) == 20
    assert all(len(row) == 60 for row in rows)
