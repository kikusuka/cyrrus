"""Frame harness and golden-frame contract."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from cyrrus.tui import goldens, harness


class Hello(App):
    def compose(self) -> ComposeResult:
        yield Static("hello frame", id="hello")


def test_compositor_render_at_three_sizes():
    for width, height in ((80, 24), (120, 30), (60, 20)):
        text = harness.render_screen(Hello(), (width, height))
        rows = text.splitlines()
        assert len(rows) == height
        assert all(len(row) == width for row in rows)
        assert "hello frame" in rows[0] or "hello frame" in text


def test_pyte_capture_is_exact_terminal_screen():
    text = harness.render_screen(Hello(), (80, 24), use_pyte=True)
    rows = text.splitlines()
    assert len(rows) == 24
    assert all(len(row) == 80 for row in rows)
    assert "hello frame" in rows[0]


def test_widget_goldens_match_exactly():
    for scene, width, height in goldens.cases():
        actual = goldens.render_case(scene, (width, height))
        harness.compare_golden(goldens.golden_name(scene, width, height), actual, width)


def test_size_parser_and_oracle():
    assert harness.parse_size("80x24") == (80, 24)
    assert harness.parse_size("120X30") == (120, 30)
    try:
        harness.parse_size("wide")
    except ValueError:
        pass
    else:
        raise AssertionError("bad size accepted")
