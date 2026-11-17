"""Widget contracts ported from the Breezy Trace design."""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Button, Input

from cyrrus.tui import widgets


def test_responsive_thresholds_and_footer_clipping():
    assert widgets.layout_mode(120) == "wide"
    assert widgets.layout_mode(100) == "wide"
    assert widgets.layout_mode(99) == "medium"
    assert widgets.layout_mode(81) == "medium"
    assert widgets.layout_mode(80) == "narrow"
    assert widgets.layout_mode(60) == "narrow"
    assert widgets.columns_for(120) == 2
    assert widgets.columns_for(80) == 1
    assert widgets.tab_labels(120)[1] == "Overview"
    assert widgets.tab_labels(80)[1] == "Over"

    hints = widgets.HOME_HINTS
    wide = widgets.footer_line(hints, 120)
    narrow = widgets.footer_line(hints, 80)
    project60 = widgets.footer_line(widgets.SESSION_HINTS, 60)
    assert wide.endswith("\u258f^p palette")
    assert narrow.endswith("\u258f^p palette")
    assert len(wide) <= 120 and len(narrow) <= 80 and len(project60) <= 60
    assert "del Remove" in narrow
    assert project60.endswith("R Run")


def test_panel_tabs_table_and_scrollbar_css():
    panel = widgets.Panel("SESSIONS")
    assert panel.border_title == "SESSIONS"
    assert "border: round" in widgets.Panel.DEFAULT_CSS
    assert "reverse bold" in widgets.MonoTable.DEFAULT_CSS
    assert "scrollbar-size-vertical: 1" in widgets.SCROLLBAR_CSS

    table = widgets.MonoTable()
    assert table.cursor_type == "row"
    assert table.cell_padding == 1
    assert table.show_header is True


def test_footer_renders_bold_keys():
    text = widgets.footer_text(widgets.HOME_HINTS, 120)
    plain = text.plain
    assert plain.startswith("q Quit")
    assert plain.endswith("\u258f^p palette")


def test_help_overlay_keys():
    screen = widgets.HelpOverlay()
    keys = dict(screen.key_rows())
    assert keys["q"] == "Quit"
    assert keys["?"] == "Help"
    assert screen.BINDINGS


def _run_confirm(presses):
    result = {}

    class Demo(App):
        def on_mount(self):
            self.push_screen(
                widgets.ConfirmDialog("Forget session 'work'?", confirm_label="Forget"),
                callback=lambda value: result.setdefault("value", value),
            )

    async def scenario():
        async with Demo().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            for key in presses:
                await pilot.press(key)
                await pilot.pause()
        return result.get("value")

    return asyncio.run(scenario())


def test_confirm_cancel_is_focused_and_enter_cancels():
    assert _run_confirm(["enter"]) is False


def test_confirm_tab_then_enter_confirms():
    assert _run_confirm(["tab", "enter"]) is True


def test_toast_stack_is_inverse_and_five_seconds():
    class Demo(App):
        def compose(self) -> ComposeResult:
            yield widgets.ToastStack(id="toasts")

    async def scenario():
        app = Demo()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            stack = app.query_one(widgets.ToastStack)
            stack.add_toast("Fact forgotten")
            await pilot.pause()
            return stack, list(stack.query(widgets.Toast))

    stack, toasts = asyncio.run(scenario())
    assert widgets.ToastStack.DEFAULT_TIMEOUT == 5.0
    assert len(toasts) == 1
    assert toasts[0].has_class("toast")
    assert "reverse bold" in widgets.Toast.DEFAULT_CSS


def test_form_action_row_and_enter_to_save():
    saved = {}

    class Demo(App):
        def on_mount(self):
            self.push_screen(
                widgets.FormDialog(
                    "New fact",
                    [("key", "Key", ""), ("value", "Value", "")],
                    on_save=lambda values: saved.update(values),
                ),
            )

    async def scenario():
        async with Demo().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.press("enter")
            await pilot.press("b")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert saved == {"key": "a", "value": "b"}
    assert "form-actions" in widgets.FormDialog.DEFAULT_CSS
    assert widgets.FORM_ACTION_GAP == 2
