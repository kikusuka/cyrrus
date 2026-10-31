"""Small, injectable terminal widgets used by setup and the home screen."""
import getpass
import sys
import time

from .caps import Caps
from .theme import Theme


class UI:
    """I/O seams for terminal screens; pass fakes in tests."""
    def __init__(self, key_source=None, output=None, caps=None, clock=None, input_fn=None, hidden_fn=None):
        self.key_source = key_source
        self.output = output or sys.stdout
        self.caps = caps or Caps()
        self.clock = clock or time.sleep
        self.input_fn = input_fn or input
        self.hidden_fn = hidden_fn or getpass.getpass
        self.theme = Theme(self.caps)

    def write(self, text=""):
        self.output.write(str(text) + "\n")

    def key(self):
        return self.key_source() if self.key_source else None


def panel(ui, title, lines):
    glyph = ui.theme.glyphs
    width = max([len(title)] + [len(str(line)) for line in lines]) + 4
    ui.write(glyph.corner_tl + glyph.hline * width + glyph.corner_tr)
    ui.write(glyph.vline + " " + title.ljust(width - 2) + " " + glyph.vline)
    for line in lines:
        ui.write(glyph.vline + " " + str(line).ljust(width - 2) + " " + glyph.vline)
    ui.write(glyph.corner_bl + glyph.hline * width + glyph.corner_br)


def step_header(ui, current, total, title):
    ui.write(ui.theme.status("Step %s of %s" % (current, total), "info") + " — " + title)


def footer(ui):
    ui.write("↑/↓ move  Enter select  Esc back  q quit")


def select(ui, prompt, options, default=0):
    """Select ``(label, value)`` options using keys or a numbered fallback."""
    if not options:
        raise ValueError("select requires options")
    index = default
    if ui.key_source and ui.caps.is_tty:
        while True:
            ui.write(prompt)
            for number, item in enumerate(options):
                label = item[0] if isinstance(item, tuple) else item
                ui.write(("> " if number == index else "  ") + str(label))
            key = ui.key()
            if key in ("UP", "\x1b[A"): index = (index - 1) % len(options)
            elif key in ("DOWN", "\x1b[B"): index = (index + 1) % len(options)
            elif key in ("ENTER", "\r", "\n"): break
            elif key in ("q", "Q", "ESC", "\x1b"): return None
    else:
        ui.write(prompt)
        for number, item in enumerate(options, 1):
            label = item[0] if isinstance(item, tuple) else item
            ui.write("%s) %s" % (number, label))
        answer = ui.input_fn("Choice [%s]: " % (default + 1)).strip()
        if answer.lower() in ("q", "quit"): return None
        try: index = int(answer) - 1 if answer else default
        except ValueError: index = default
        index = min(max(index, 0), len(options) - 1)
    chosen = options[index]
    return chosen[1] if isinstance(chosen, tuple) else chosen


def text_input(ui, prompt, default=""):
    value = ui.input_fn("%s%s: " % (prompt, " [%s]" % default if default else "")).strip()
    return value or default


def hidden_input(ui, prompt):
    return ui.hidden_fn(prompt + ": ")


def confirm(ui, prompt, default=False):
    suffix = "Y/n" if default else "y/N"
    answer = ui.input_fn("%s [%s]: " % (prompt, suffix)).strip().lower()
    return default if not answer else answer in ("y", "yes")


def spinner(ui, label, action):
    ui.write(label + "…")
    try:
        result = action()
    except Exception:
        ui.write(ui.theme.status("failed", "error"))
        raise
    ui.write(ui.theme.status("done", "ok"))
    return result
