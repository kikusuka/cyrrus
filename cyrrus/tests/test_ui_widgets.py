from io import StringIO

from cyrrus.ui.caps import Caps
from cyrrus.ui.widgets import UI, select, text_input


def test_numbered_select_and_default_input():
    answers = iter(["2", ""])
    ui = UI(output=StringIO(), caps=Caps(is_tty=False), input_fn=lambda _: next(answers))
    assert select(ui, "Pick", [("one", 1), ("two", 2)]) == 2
    assert text_input(ui, "Name", "Ada") == "Ada"


def test_scripted_arrow_select():
    keys = iter(["DOWN", "ENTER"])
    ui = UI(key_source=lambda: next(keys), output=StringIO(), caps=Caps(is_tty=True))
    assert select(ui, "Pick", ["one", "two"]) == "two"


def test_panel_lines_equal_width_at_80_columns():
    """Every row inside the panel is padded to the same width; right border in one column."""
    from cyrrus.ui.widgets import panel
    out = StringIO()
    ui = UI(output=out, caps=Caps(is_tty=False, unicode=True, width=80, height=24))
    panel(ui, "status", ["Gateway:  inject", "Model:    none", "Memory:   keyword", "Renderer: default"])
    body = out.getvalue().splitlines()
    rows = body[1:-1]
    assert rows, "panel should render at least the title row"
    widths = {len(row) for row in rows}
    assert len(widths) == 1, "rows not equally wide: %s" % widths
    right_borders = {row[-1] for row in rows}
    assert len(right_borders) == 1, "right border not in one column: %s" % right_borders


def test_panel_uses_unicode_when_supported_and_ascii_fallback():
    """Same panel style as the wizard: rounded Unicode when supported, ASCII otherwise."""
    from cyrrus.ui.widgets import panel

    def borders(caps):
        out = StringIO()
        ui = UI(output=out, caps=caps)
        panel(ui, "t", ["one line"])
        return out.getvalue().splitlines()[0]

    unicode_first = borders(Caps(is_tty=False, unicode=True, width=80, height=24))
    ascii_first = borders(Caps(is_tty=False, unicode=False, width=80, height=24))
    assert unicode_first.startswith("╭") and unicode_first.endswith("╮"), unicode_first
    assert ascii_first.startswith("+") and ascii_first.endswith("+"), ascii_first
    assert all(ord(ch) < 128 for ch in ascii_first)
