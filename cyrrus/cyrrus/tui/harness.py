"""Frame test harness: Textual Pilot -> pyte (exact) or compositor text.

The pyte path is the capture method used for the design study: a non-headless
``HeadlessDriver`` feeds every ANSI write to a VT screen.  The compositor path
needs no third-party package and is what ``--dump-frame`` uses inside a
packaged binary.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = PACKAGE_ROOT / "tests" / "golden"


def make_term_driver(base):
    """Subclass the *original* headless driver before it is patched."""
    import pyte

    class _TermDriver(base):
        @property
        def is_headless(self) -> bool:
            return False

        def __init__(self, app, **options):
            super().__init__(app, **options)
            width, height = self._get_terminal_size()
            self.term = pyte.Screen(width, height)
            self.stream = pyte.Stream(self.term)
            self.raw_chunks: List[str] = []

        def write(self, data: str) -> None:
            self.raw_chunks.append(data)
            self.stream.feed(data)

        def plain(self) -> str:
            width = self.term.columns
            return "\n".join(line.ljust(width) for line in self.term.display)

        def raw(self) -> str:
            return "".join(self.raw_chunks)

    return _TermDriver


def parse_size(value: str) -> Tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        size = (int(width), int(height))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("size must look like 80x24") from exc
    if size[0] < 20 or size[1] < 8:
        raise ValueError("size is too small")
    return size


def _compositor_text(app, width: int) -> str:
    update = app.screen._compositor.render_full_update(simplify=True)
    rows: List[str] = []
    for row in update.strips:
        line = []
        for strip in row:
            for segment in strip:
                line.append(segment.text)
        text = "".join(line).replace("\r", "").replace("\n", "")
        rows.append(text[:width].ljust(width))
    return "\n".join(rows)


async def _run(app, size, keys, use_pyte):
    import textual.drivers.headless_driver as headless

    patched = None
    if use_pyte:
        patched = headless.HeadlessDriver
        headless.HeadlessDriver = make_term_driver(patched)
    try:
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
                await pilot.pause()
            if use_pyte:
                return app._driver.plain()
            return _compositor_text(app, size[0])
    finally:
        if patched is not None:
            headless.HeadlessDriver = patched


def render_screen(
    app,
    size: Tuple[int, int] = (80, 24),
    keys: Sequence[str] = (),
    *,
    use_pyte: bool = False,
) -> str:
    """Drive ``app`` and return its final screen as plain text."""
    return asyncio.run(_run(app, size, list(keys), use_pyte))


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / name


def read_golden(name: str) -> str:
    return golden_path(name).read_text(encoding="utf-8")


def normalise_frame(text: str, width: Optional[int] = None) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    rows = text.split("\n")
    if width is not None:
        rows = [row[:width].ljust(width) for row in rows]
    return "\n".join(rows) + "\n"


def compare_golden(name: str, actual: str, width: Optional[int] = None) -> None:
    path = golden_path(name)
    if not path.exists():
        raise AssertionError(
            "missing golden %s; regenerate with: python -m cyrrus.tui.goldens --write" % path
        )
    expected = normalise_frame(path.read_text(encoding="utf-8"), width)
    got = normalise_frame(actual, width)
    if got != expected:
        import difflib

        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                got.splitlines(),
                fromfile=str(path),
                tofile="actual",
                lineterm="",
            )
        )
        raise AssertionError("golden mismatch for %s\n%s" % (name, diff))
