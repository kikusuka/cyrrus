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
