"""Render every setup screen and the home menu into a review file.

Run from the project folder::

    python devtools/preview_wizard.py

The output goes to ``C:/Users/DELL/cyrrus_scratch/wizard_preview.txt``. Network
calls are faked and wizard file writes happen in a temporary directory.
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cyrrus.cli as cli
import cyrrus.setup as setup
import cyrrus.ui.caps as caps_module
import cyrrus.ui.widgets as widgets
from cyrrus.ui import anim
from cyrrus.ui.caps import COLOR_16, COLOR_NONE, Caps
from cyrrus.ui.widgets import UI

OUTPUT = Path(r"C:\Users\DELL\cyrrus_scratch\wizard_preview.txt")

FAKE_SERVICES = {
    "ollama": True, "lmstudio": False, "llamacpp": False, "openai": False,
    "mistral": False, "groq": False, "openrouter": False, "gemini": False,
    "anthropic": False, "custom": False,
}

WIZARD_INPUTS = [
    "", "", "", "", "", "", "", "", "", "", "", "", "", "", "y", "", "",
]

SAMPLE_CONFIG = {
    "provider": {
        "service": "ollama",
        "model": "qwen2.5-coder:0.5b",
        "base_url": "http://127.0.0.1:11434/v1",
    },
    "gateway": {"mode": "inject", "host": "127.0.0.1", "port": 8787, "session": "default"},
    "memory": {"retrieval": "keyword", "db_path": None},
    "context": {"renderer": "default", "max_context_tokens": 4000},
    "ui": {"onboarded": True, "animation": "auto"},
}


def _caps(ansi):
    return Caps(
        is_tty=False, color_depth=COLOR_16 if ansi else COLOR_NONE,
        unicode=True, width=80, height=24, ci=False, reduced_motion=False,
        ansi=ansi, term_dumb=False,
    )


def _fake_network():
    saved = {
        "detect_services": setup.detect_services,
        "list_models": setup.list_models,
        "check_connection": setup.check_connection,
        "_detect_hybrid_available": setup._detect_hybrid_available,
    }
    setup.detect_services = lambda timeout=1.0: dict(FAKE_SERVICES)
    setup.list_models = lambda service_id, base_url=None, timeout=5.0: {
        "success": True,
        "models": ["qwen2.5-coder:0.5b", "llama3.2"],
        "error": None,
    }
    setup.check_connection = lambda config, timeout=10.0: {
        "success": True, "reachable": True, "completion_ok": True,
        "error": None, "service": "ollama", "model": "qwen2.5-coder:0.5b",
    }
    setup._detect_hybrid_available = lambda: False
    return saved


def _restore_network(saved):
    for name, value in saved.items():
        setattr(setup, name, value)


def render_wizard(caps):
    out = StringIO()
    answers = list(WIZARD_INPUTS)
    ui = UI(output=out, caps=caps, input_fn=lambda prompt="": answers.pop(0) if answers else "",
            hidden_fn=lambda prompt="": "")
    saved = _fake_network()
    old_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory(prefix="cyrrus-preview-") as folder:
            os.chdir(folder)
            try:
                setup.run_setup(ui, non_interactive=False, plain=not caps.ansi, force=True)
            finally:
                os.chdir(old_cwd)
    finally:
        _restore_network(saved)
    lines = [line for line in out.getvalue().splitlines() if "cyrrus-preview-" not in line]
    return "\n".join(lines) + "\n"


def render_home(caps):
    buffer = StringIO()
    ui = UI(output=buffer, caps=caps, input_fn=lambda prompt="": "8",
            hidden_fn=lambda prompt="": "")
    saved = {
        "load_config": cli.load_config,
        "detect_caps": caps_module.detect_caps,
        "UI": widgets.UI,
    }
    cli.load_config = lambda **kwargs: dict(SAMPLE_CONFIG)
    caps_module.detect_caps = lambda: caps
    widgets.UI = lambda caps=None: ui
    try:
        with redirect_stdout(buffer):
            cli.cmd_home(SimpleNamespace(config=None))
    finally:
        cli.load_config = saved["load_config"]
        caps_module.detect_caps = saved["detect_caps"]
        widgets.UI = saved["UI"]
    return buffer.getvalue()


def render_logo(caps):
    frames = anim.logo_frames(caps)
    return frames[0][0] if frames else ""


def main():
    sections = []
    for label, caps in (("PLAIN", _caps(False)), ("ANSI", _caps(True))):
        sections.append("=== BREEZY LABS LOGO - %s 80x24 ===" % label)
        sections.append(render_logo(caps))
        sections.append("")
        sections.append("=== WIZARD (ALL 7 SCREENS) - %s 80x24 ===" % label)
        sections.append(render_wizard(caps))
        sections.append("=== HOME MENU - %s 80x24 ===" % label)
        sections.append(render_home(caps))
        sections.append("")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print("Wrote %s" % OUTPUT)


if __name__ == "__main__":
    main()
