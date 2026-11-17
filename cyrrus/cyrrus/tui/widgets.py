"""Textual widgets for the monochrome cyrrus interface.

Ported from the Breezy Trace design study: round titled panels, a tab bar,
reverse-selection tables, one-line key hints, an inverse toast stack, a
cancel-first confirm dialog, forms, a one-column scrollbar, and modal
screens with a composited (opaque-cell) backdrop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static


# ---------------------------------------------------------------------------
# Layout rules from the brief

WIDE_WIDTH = 100
NARROW_WIDTH = 80
FORM_ACTION_GAP = 2


def layout_mode(width: int) -> str:
    if width >= WIDE_WIDTH:
        return "wide"
    if width <= NARROW_WIDTH:
        return "narrow"
    return "medium"


def columns_for(width: int) -> int:
    return 2 if width >= WIDE_WIDTH else 1


def tab_labels(width: int) -> List[str]:
    if width <= NARROW_WIDTH:
        return ["Lobby", "Over", "Facts", "Trace", "Hist", "Set"]
    return ["Lobby", "Overview", "Facts", "Trace", "History", "Settings"]


# ---------------------------------------------------------------------------
# Key hints and footer


@dataclass(frozen=True)
class KeyHint:
    key: str
    description: str


HOME_HINTS = [
    KeyHint("q", "Quit"),
    KeyHint("?", "Help"),
    KeyHint("o", "Add"),
    KeyHint("n", "New"),
    KeyHint("c", "Clone"),
    KeyHint("del", "Remove"),
    KeyHint("/", "Search"),
    KeyHint("r", "Refresh"),
]
SESSION_HINTS = [
    KeyHint("q", "Quit"),
    KeyHint("?", "Help"),
    KeyHint("n", "New"),
    KeyHint("d", "Forget"),
    KeyHint("e", "Export"),
    KeyHint("/", "Search"),
    KeyHint("R", "Run"),
    KeyHint("1-5", "Tabs"),
    KeyHint("esc", "Lobby"),
]
PALETTE_HINT = "\u258f^p palette"
PALETTE_STYLE = "dim"


def _plain(hint: KeyHint) -> str:
    return "%s %s" % (hint.key, hint.description)


def _select_hints(hints: Sequence[KeyHint], width: int) -> Tuple[List[KeyHint], bool]:
    selected: List[KeyHint] = []
    used = 0
    for hint in hints:
        piece = len(_plain(hint)) + (2 if selected else 0)
        if used + piece > width:
            break
        selected.append(hint)
        used += piece
    palette = False
    if width >= 70:
        while selected:
            size = len("  ".join(_plain(h) for h in selected))
            if size + 1 + len(PALETTE_HINT) <= width:
                palette = True
                break
            selected.pop()
    return selected, palette


def footer_text(hints: Sequence[KeyHint], width: int) -> Text:
    selected, palette = _select_hints(hints, width)
    text = Text()
    for index, hint in enumerate(selected):
        if index:
            text.append("  ")
        text.append(hint.key, style="bold")
        text.append(" " + hint.description)
    if palette:
        text.append(" " + PALETTE_HINT, style="dim")
    return text


def footer_line(hints: Sequence[KeyHint], width: int) -> str:
    return footer_text(hints, width).plain


class KeyHints(Static):
    """A one-line footer; the framework palette hint is always last."""

    def __init__(
        self,
        hints: Sequence[KeyHint] = HOME_HINTS,
        *,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self.hints = list(hints)

    def on_resize(self) -> None:
        self.refresh()

    def render(self) -> Text:
        return footer_text(self.hints, max(1, self.size.width))


# ---------------------------------------------------------------------------
# Panels and tabs


class Panel(Container):
    """A round-border titled panel."""

    DEFAULT_CSS = """
    Panel {
        border: round $text-muted;
        background: $background;
        color: $foreground;
        padding: 0 1;
        height: auto;
    }
    Panel:focus-within {
        border: round $foreground;
    }
    """

    def __init__(self, title: str = "", *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.border_title = title


class TabBar(Static):
    DEFAULT_CSS = """
    TabBar { height: 1; background: $background; color: $foreground; }
    """

    active = reactive(0)

    def __init__(
        self,
        tabs: Optional[Sequence[str]] = None,
        *,
        return_label: str = "Lobby",
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self.tabs = list(tabs or [])
        self.return_label = return_label

    def set_active(self, index: int) -> None:
        self.active = max(0, min(len(self.tabs) - 1, index))

    def watch_active(self, _old: int, _new: int) -> None:
        self.refresh()

    def render(self) -> Text:
        width = self.app.size.width if self.app else 120
        labels = tab_labels(width)
        text = Text()
        text.append("\u2039 " + self.return_label, style="dim")
        for index, label in enumerate(self.tabs or labels[1:]):
            text.append("  ")
            style = "bold underline" if index == self.active else "dim"
            text.append(label, style=style)
        return text


# ---------------------------------------------------------------------------
# Table


class MonoTable(DataTable):
    DEFAULT_CSS = """
    MonoTable {
        background: $background;
        color: $foreground;
        height: auto;
        max-height: 100%;
    }
    MonoTable > .datatable--header {
        background: $surface;
        color: $text-muted;
        text-style: bold;
    }
    MonoTable > .datatable--cursor {
        background: $foreground;
        color: $background;
        text-style: reverse bold;
    }
    MonoTable > .datatable--hover {
        background: $foreground;
        color: $background;
    }
    """

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("cursor_type", "row")
        kwargs.setdefault("cell_padding", 1)
        kwargs.setdefault("show_row_labels", False)
        kwargs.setdefault("zebra_stripes", False)
        super().__init__(**kwargs)


SCROLLBAR_CSS = """
VerticalScroll, ScrollableContainer {
    scrollbar-size-vertical: 1;
    scrollbar-size-horizontal: 0;
    scrollbar-background: $surface;
    scrollbar-color: $text-muted;
    scrollbar-color-hover: $text-muted;
    scrollbar-color-active: $primary;
}
MonoTable {
    scrollbar-size-vertical: 1;
    scrollbar-size-horizontal: 0;
    scrollbar-background: $surface;
    scrollbar-color: $text-muted;
    scrollbar-color-hover: $text-muted;
    scrollbar-color-active: $primary;
}
"""


# ---------------------------------------------------------------------------
# Toasts


class Toast(Static):
    DEFAULT_CSS = """
    Toast {
        background: $foreground;
        color: $background;
        text-style: reverse bold;
        padding: 0 1;
        width: auto;
        height: 1;
        margin-top: 1;
    }
    """


class ToastStack(Vertical):
    DEFAULT_TIMEOUT = 5.0

    DEFAULT_CSS = """
    ToastStack {
        dock: bottom;
        layer: toasts;
        width: 100%;
        height: auto;
        max-height: 8;
        align-horizontal: right;
        padding: 0 1;
    }
    """

    def add_toast(self, message: str, timeout: float = DEFAULT_TIMEOUT) -> Toast:
        toast = Toast(Text.assemble(("! ", "bold"), message), classes="toast")
        self.mount(toast)
        if timeout and timeout > 0:
            self.set_timer(timeout, lambda: self._expire(toast))
        return toast

    def _expire(self, toast: Toast) -> None:
        if toast.is_mounted:
            toast.remove()


# ---------------------------------------------------------------------------
# Modal screens


class BackdropScreen(ModalScreen):
    """A modal screen; the compositor flattens its 70% backdrop to cells."""

    DEFAULT_CSS = """
    BackdropScreen {
        align: center middle;
        background: $background 70%;
    }
    """


class ConfirmDialog(ModalScreen):
    """Cancel is focused; Enter therefore cancels unless Tab moves focus."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
        background: $background 70%;
    }
    ConfirmDialog > .dialog {
        width: 52;
        max-width: 90%;
        height: auto;
        border: round $foreground;
        background: $background;
        padding: 1 2;
    }
    ConfirmDialog .dialog-question {
        text-style: bold;
        margin-bottom: 1;
    }
    ConfirmDialog .dialog-actions {
        height: auto;
        align-horizontal: right;
        padding: 1 2 0 2;
    }
    ConfirmDialog Button {
        margin-left: 2;
        min-width: 10;
    }
    """

    def __init__(
        self,
        question: str,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Static(self.question, classes="dialog-question")
            with Horizontal(classes="dialog-actions"):
                yield Button(self.cancel_label, id="cancel")
                yield Button(self.confirm_label, id="confirm")
            yield Static("", id="dialog-hint", classes="faint")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class FormDialog(ModalScreen):
    """Label + Input rows; Enter advances, then saves.  Esc cancels."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    FormDialog {
        align: center middle;
        background: $background 70%;
    }
    FormDialog > .dialog {
        width: 64;
        max-width: 92%;
        height: auto;
        border: round $foreground;
        background: $background;
        padding: 1 2;
    }
    FormDialog .form-title {
        text-style: bold;
        margin-bottom: 1;
    }
    FormDialog Label {
        color: $text-muted;
        text-style: dim;
    }
    FormDialog Input {
        margin-bottom: 1;
    }
    FormDialog .form-error {
        color: $foreground;
        text-style: bold;
        height: auto;
    }
    FormDialog .form-actions {
        height: auto;
        align-horizontal: right;
        padding: 1 2 0 2;
    }
    FormDialog Button {
        margin-left: 2;
        min-width: 10;
    }
    """

    def __init__(
        self,
        title: str,
        fields: Sequence[Tuple[str, str, str]],
        *,
        on_save: Optional[Callable[[dict], None]] = None,
        validate: Optional[Callable[[dict], Optional[str]]] = None,
        save_label: str = "Save",
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.fields = list(fields)
        self.on_save_callback = on_save
        self.validate_callback = validate
        self.save_label = save_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Container(classes="dialog"):
            yield Static(self.title_text, classes="form-title")
            for name, label, value in self.fields:
                yield Label(label)
                yield Input(value=value, id="field-" + name)
            yield Static("", id="form-error", classes="form-error")
            with Horizontal(classes="form-actions"):
                yield Button(self.cancel_label, id="cancel")
                yield Button(self.save_label, id="save")

    def on_mount(self) -> None:
        inputs = list(self.query(Input))
        if inputs:
            inputs[0].focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inputs = list(self.query(Input))
        index = inputs.index(event.input)
        if index + 1 < len(inputs):
            inputs[index + 1].focus()
        else:
            self.save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.save()
        else:
            self.dismiss(None)

    def values(self) -> dict:
        result = {}
        for name, _label, _value in self.fields:
            result[name] = self.query_one("#field-" + name, Input).value
        return result

    def save(self) -> None:
        values = self.values()
        if self.validate_callback:
            error = self.validate_callback(values)
            if error:
                self.query_one("#form-error", Static).update(error)
                return
        if self.on_save_callback:
            self.on_save_callback(values)
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


HELP_ROWS: List[Tuple[str, str]] = [
    ("q", "Quit"),
    ("?", "Help"),
    ("T", "Theme"),
    ("r", "Refresh"),
    ("/", "Search"),
    ("o", "Add repo"),
    ("n", "New"),
    ("Enter", "Open"),
    ("Delete", "Forget"),
    ("1-5", "Session tabs"),
    ("Esc", "Back"),
    ("^p", "Command palette"),
]


class HelpOverlay(ModalScreen):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("?", "close", "Close"),
        ("q", "close", "Close"),
    ]

    DEFAULT_CSS = """
    HelpOverlay {
        align: center middle;
        background: $background 70%;
    }
    HelpOverlay > .help-dialog {
        width: 72;
        max-width: 94%;
        height: auto;
        max-height: 90%;
        border: round $foreground;
        background: $background;
        padding: 1 2;
    }
    HelpOverlay .help-title {
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def key_rows(self) -> List[Tuple[str, str]]:
        return list(HELP_ROWS)

    def compose(self) -> ComposeResult:
        with Container(classes="help-dialog"):
            yield Static("Keys", classes="help-title")
            yield Static(self._body())
            yield Static("Esc or ? to close", classes="faint")

    def _body(self) -> Text:
        text = Text()
        width = max(len(key) for key, _ in HELP_ROWS) + 2
        for key, description in HELP_ROWS:
            text.append(key.ljust(width), style="bold")
            text.append(description)
            text.append("\n")
        return text

    def action_close(self) -> None:
        self.dismiss(None)


class PickerBackdrop(BackdropScreen):
    """The project picker uses the brief's deeper 80% backdrop."""

    DEFAULT_CSS = """
    PickerBackdrop {
        align: center middle;
        background: $background 80%;
    }
    """

