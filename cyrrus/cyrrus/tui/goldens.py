"""Reproducible monochrome widget goldens.

Regenerate:
    python -m cyrrus.tui.goldens --write
Check:
    python -m cyrrus.tui.goldens
"""
from __future__ import annotations

import argparse
from typing import Iterable, List, Tuple

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from . import harness, theme, widgets


SIZES: Tuple[Tuple[int, int], ...] = ((80, 24), (120, 30), (60, 20))
SCENES = ("gallery", "toast", "confirm", "form", "help")


class GalleryApp(App):
    CSS = theme.theme_css() + widgets.SCROLLBAR_CSS + """
    Screen { layout: vertical; overflow: hidden; }
    #gallery-top {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #gallery-panel { height: 1fr; }
    #gallery-table { height: 1fr; }
    KeyHints {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, scene: str = "gallery") -> None:
        super().__init__()
        self.scene = scene

    def compose(self) -> ComposeResult:
        yield Static(
            Text.assemble(
                ("cyrrus", "bold"),
                "  \u00b7  by Breezy Labs  3 sessions  \u00b7  2 need attention   ? help",
            ),
            id="gallery-top",
        )
        yield widgets.TabBar(["Overview", "Facts", "Trace", "History", "Settings"])
        with widgets.Panel("SESSIONS", id="gallery-panel"):
            yield widgets.MonoTable(id="gallery-table")
        yield widgets.KeyHints(widgets.HOME_HINTS)
        if self.scene == "toast":
            yield widgets.ToastStack()

    def on_mount(self) -> None:
        self.register_theme(theme.build_theme("light"))
        self.theme = "cyrrus-light"
        table = self.query_one(widgets.MonoTable)
        table.add_columns("SESSION", "FACTS", "LAST ACTIVE", "30 DAYS")
        table.add_rows(
            [
                ("work", "12", "2m ago", "\u00b7\u2591\u2592\u2593\u2588\u00b7\u2592"),
                ("personal", "7", "1d ago", "\u00b7\u00b7\u2591\u2592\u00b7\u00b7\u2588"),
                ("scratch", "3", "9d ago", "\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u2591"),
            ]
        )
        table.focus()
        self.query_one(widgets.TabBar).set_active(1)
        stack = None
        if self.scene == "toast":
            stack = self.query_one(widgets.ToastStack)
        if self.scene == "toast":
            stack.add_toast("Fact forgotten")
        elif self.scene == "confirm":
            self.push_screen(
                widgets.ConfirmDialog("Forget session 'work'?", confirm_label="Forget")
            )
        elif self.scene == "form":
            self.push_screen(
                widgets.FormDialog(
                    "New fact",
                    [("key", "Key", "editor"), ("value", "Value", "Use tabs")],
                )
            )
        elif self.scene == "help":
            self.push_screen(widgets.HelpOverlay())


def cases() -> Iterable[Tuple[str, int, int]]:
    for scene in SCENES:
        for width, height in SIZES:
            yield scene, width, height


def golden_name(scene: str, width: int, height: int) -> str:
    return "%s_%dx%d.txt" % (scene, width, height)


def render_case(scene: str, size: Tuple[int, int]) -> str:
    return harness.render_screen(GalleryApp(scene), size)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="cyrrus widget goldens")
    parser.add_argument("--write", action="store_true", help="write golden files")
    args = parser.parse_args(argv)

    written = 0
    failures = 0
    harness.GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for scene, width, height in cases():
        name = golden_name(scene, width, height)
        actual = harness.normalise_frame(render_case(scene, (width, height)), width)
        path = harness.golden_path(name)
        if args.write:
            path.write_text(actual, encoding="utf-8", newline="\n")
            written += 1
            print("wrote %s" % path)
        else:
            try:
                harness.compare_golden(name, actual, width)
                print("ok    %s" % name)
            except AssertionError as exc:
                failures += 1
                print(str(exc))
    if args.write:
        print("%d golden frame(s) written" % written)
        return 0
    print("%d failure(s)" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())


