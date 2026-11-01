"""Tests for the guided onboarding wizard (``cyrrus setup``).

Everything is scripted: no real network, no real model calls, no interactive
terminal. Writes only happen inside ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cyrrus.cli import main
from cyrrus.setup import run_setup, snippet
from cyrrus.ui.caps import Caps, COLOR_NONE
from cyrrus.ui.theme import Theme
from cyrrus.ui.widgets import UI


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

FAKE_SERVICES_DETECTED = {
    "ollama": True,
    "lmstudio": False,
    "llamacpp": False,
    "openai": False,
    "mistral": False,
    "groq": False,
    "openrouter": False,
    "gemini": False,
    "anthropic": False,
    "custom": False,
}


def _patch_network(monkeypatch):
    monkeypatch.setattr("cyrrus.setup.detect_services", lambda timeout=1.0: dict(FAKE_SERVICES_DETECTED))
    monkeypatch.setattr(
        "cyrrus.setup.list_models",
        lambda service_id, base_url=None, timeout=5.0: {
            "success": True,
            "models": ["qwen2.5-coder:0.5b", "llama3.2"],
            "error": None,
        },
    )
    monkeypatch.setattr(
        "cyrrus.setup.check_connection",
        lambda config, timeout=10.0: {
            "success": True,
            "reachable": True,
            "completion_ok": True,
            "error": None,
            "service": "ollama",
            "model": "qwen2.5-coder:0.5b",
        },
    )
    monkeypatch.setattr("cyrrus.setup._detect_hybrid_available", lambda: False)


_NUMBERED_SCRIPT = [
    "",      # step 1: press enter (welcome)
    "",      # step 2: goal selection (default gateway)
    "",      # step 3: service = ollama (default)
    "",      # step 3: base_url = default
    "",      # step 3: model = qwen2.5-coder:0.5b (default)
    "",      # step 4: storage = per-user (default)
    "",      # step 4: retrieval = keyword (default)
    "",      # step 4: max_facts = default 50
    "",      # step 5: renderer = default (default)
    "",      # step 5: preset = medium (default)
    "",      # step 5: starter = assistant (default)
    "",      # step 6: port = 8787 (default)
    "",      # step 6: mode = inject (default)
    "",      # step 6: session = default
    "y",     # step 7: save = yes
    "",      # step 7: scope = project (default)
    "",      # buffer: extra read compensation
]


class ScriptedUI:
    """UI that feeds answers from a list (numbered mode) or keys (arrow mode)."""

    def __init__(self, inputs=None, keys=None, tty=True):
        self.output = __import__("io").StringIO()
        self._inputs = list(inputs or [])
        self._read_count = 0
        self._total = len(self._inputs) if inputs else 0
        self._keys = list(keys or [])
        self.key_source = None
        self.caps = Caps(
            is_tty=tty,
            color_depth=COLOR_NONE,
            unicode=False,
            width=80,
            height=24,
            ci=False,
            reduced_motion=False,
            ansi=False,
            term_dumb=False,
        )
        self.theme = Theme(self.caps)

    def write(self, text=""):
        self.output.write(str(text) + "\n")

    def input_fn(self, prompt=""):
        self._read_count += 1
        if not self._inputs:
            raise EOFError("no more scripted inputs (total %d, read %d)" % (self._total, self._read_count))
        return self._inputs.pop(0)

    def hidden_fn(self, prompt=""):
        return self.input_fn(prompt)

    def key(self):
        if not self._keys:
            return None
        return self._keys.pop(0)

    def text(self):
        return self.output.getvalue()


# ---------------------------------------------------------------------------
# Non-interactive
# ---------------------------------------------------------------------------

def test_non_interactive_writes_files_and_redacts_secrets(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = run_setup(
        UI(caps=Caps(is_tty=False, color_depth=COLOR_NONE, unicode=False, width=80, height=24,
                     ci=False, reduced_motion=False, ansi=False, term_dumb=False)),
        non_interactive=True,
        plain=True,
        force=True,
        overrides={
            "goal": "gateway",
            "service": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:0.5b",
            "renderer": "compact",
            "max_context_tokens": 8000,
            "starter_slide": "coding",
            "gateway_mode": "inject",
            "gateway_port": 9999,
            "scope": "project",
            "yes": True,
        },
    )
    assert not result.get("cancelled")
    assert (tmp_path / "cyrrus.config.json").exists()
    assert (tmp_path / "slides.json").exists()
    config = json.loads((tmp_path / "cyrrus.config.json").read_text())
    assert config["ui"]["onboarded"] is True
    assert config["gateway"]["mode"] == "inject"
    assert config["provider"]["api_key_env"] is None  # no secret in config
    assert "sk-" not in json.dumps(config)  # no secret value in config
    assert result["dry_run"] is False


def test_non_interactive_api_key_goes_to_env_only(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    run_setup(
        UI(caps=Caps(is_tty=False, color_depth=COLOR_NONE, unicode=False, width=80, height=24,
                     ci=False, reduced_motion=False, ansi=False, term_dumb=False)),
        non_interactive=True,
        plain=True,
        force=True,
        overrides={
            "goal": "gateway",
            "service": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "api_key_env": "OPENAI_API_KEY",
            "api_key": "sk-test-SECRET-12345",
            "scope": "project",
            "yes": True,
        },
    )
    env = (tmp_path / ".env").read_text()
    assert "OPENAI_API_KEY=sk-test-SECRET-12345" in env
    config = json.loads((tmp_path / "cyrrus.config.json").read_text())
    assert config["provider"]["api_key_env"] == "*****"
    assert "sk-test-SECRET-12345" not in json.dumps(config)


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = run_setup(
        UI(caps=Caps(is_tty=False, color_depth=COLOR_NONE, unicode=False, width=80, height=24,
                     ci=False, reduced_motion=False, ansi=False, term_dumb=False)),
        non_interactive=True,
        dry_run=True,
        plain=True,
        force=True,
        overrides={
            "goal": "gateway",
            "service": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:0.5b",
            "scope": "project",
            "yes": True,
        },
    )
    assert result["dry_run"] is True
    assert not (tmp_path / "cyrrus.config.json").exists()
    assert not (tmp_path / "slides.json").exists()
    assert not (tmp_path / ".env").exists()


# ---------------------------------------------------------------------------
# Numbered (scripted input) onboarding
# ---------------------------------------------------------------------------

def test_numbered_onboarding_writes_files(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    ui = ScriptedUI(inputs=list(_NUMBERED_SCRIPT))
    result = run_setup(ui, non_interactive=False, plain=True, force=True)
    assert not result.get("cancelled")
    assert (tmp_path / "cyrrus.config.json").exists()
    assert (tmp_path / "slides.json").exists()
    out = ui.text()
    assert "Setup complete" in out
    # No secrets echoed (no api key involved for ollama).
    assert "sk-" not in out
    # Verify config was written with gateway goal.
    config = json.loads((tmp_path / "cyrrus.config.json").read_text())
    assert config["provider"]["service"] == "ollama"


def test_numbered_onboarding_outputs_snippets(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    ui = ScriptedUI(inputs=list(_NUMBERED_SCRIPT))
    result = run_setup(ui, non_interactive=False, plain=True, force=True)
    assert result["start_gateway"] is False
    assert result["test_message"] is False


# ---------------------------------------------------------------------------
# Arrow-key (scripted keys) onboarding
# ---------------------------------------------------------------------------

def test_arrow_keys_onboarding(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    # Fully key-driven: goal DOWN->library, then ENTER accepts the default for
    # every subsequent select (service ollama, model qwen, storage user,
    # retrieval keyword, renderer default, starter assistant, mode inject,
    # scope project). Text inputs come from the scripted input queue.
    ui = ScriptedUI(
        inputs=[
            "",   # step 1: press enter
            "",   # step 3: base_url default
            "",   # step 4: max_facts default
            "",   # step 5: preset default
            "",   # step 6: port default
            "",   # step 6: session default
            "y",  # step 7: save yes
        ],
        keys=[
            "DOWN", "ENTER",  # step 2 goal: library
            "ENTER",          # step 3: service = ollama (default)
            "ENTER",          # step 3: model = qwen (default)
            "ENTER",          # step 4: storage = user (default)
            "ENTER",          # step 4: retrieval = keyword (default)
            "ENTER",          # step 5: renderer = default (default)
            "ENTER",          # step 5: starter = assistant (default)
            "ENTER",          # step 6: mode = inject (default)
            "ENTER",          # step 7: scope = project (default)
        ],
        tty=True,
    )
    ui.key_source = ui.key
    result = run_setup(ui, non_interactive=False, plain=True, force=True)
    assert not result.get("cancelled")
    assert (tmp_path / "cyrrus.config.json").exists()
    config = json.loads((tmp_path / "cyrrus.config.json").read_text())
    assert config["provider"]["service"] == "ollama"
    assert config["ui"]["onboarded"] is True


# ---------------------------------------------------------------------------
# Snippets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["zed", "python", "curl"])
def test_setup_show_snippets(kind):
    out = snippet(kind, port=8787)
    assert isinstance(out, str) and len(out) > 0
    assert "127.0.0.1:8787/v1" in out


def test_setup_show_snippet_via_cli(monkeypatch, capsys):
    monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {"onboarded": True}})
    main(["setup", "show", "zed", "--port", "9999"])
    out = capsys.readouterr().out
    assert "127.0.0.1:9999/v1" in out


def test_setup_rejects_command_line_api_key(capsys):
    with pytest.raises(SystemExit, match="--api-key is unsafe"):
        main(["setup", "--api-key", "secret"])


def test_api_key_stdin_is_passed_and_not_echoed(monkeypatch, capsys):
    import io

    seen = {}

    def fake_run_setup(ui, **kwargs):
        seen.update(kwargs["overrides"])
        return {"written": [], "cancelled": False}

    monkeypatch.setattr("cyrrus.setup.run_setup", fake_run_setup)
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-secret\n"))
    main(["setup", "--non-interactive", "--api-key-env", "OPENAI_KEY", "--api-key-stdin"])
    assert seen["api_key"] == "sk-secret"
    assert seen["api_key_env"] == "OPENAI_KEY"
    assert "sk-secret" not in capsys.readouterr().out


def test_api_key_env_flag_applies_interactively(monkeypatch):
    seen = {}

    def fake_run_setup(ui, **kwargs):
        seen.update(kwargs["overrides"])
        return {"written": [], "cancelled": True}

    monkeypatch.setattr("cyrrus.setup.run_setup", fake_run_setup)
    monkeypatch.setattr("cyrrus.cli.is_interactive", lambda: True)
    main(["setup", "--api-key-env", "MY_KEY"])
    assert seen["api_key_env"] == "MY_KEY"


@pytest.mark.parametrize("onboarded,expected", [(False, "setup"), (True, "home")])
def test_plain_cyrrus_enters_setup_or_home(monkeypatch, onboarded, expected):
    import cyrrus.cli as cli

    calls = []
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda **kw: {"ui": {"onboarded": onboarded}})
    monkeypatch.setattr(cli, "cmd_setup", lambda args: calls.append("setup"))
    monkeypatch.setattr(cli, "cmd_home", lambda args: calls.append("home"))
    cli.main([])
    assert calls == [expected]


def test_tour_flag_forces_setup(monkeypatch):
    import cyrrus.cli as cli

    calls = []
    monkeypatch.setattr(cli, "is_interactive", lambda: True)
    monkeypatch.setattr(cli, "load_config", lambda **kw: {"ui": {"onboarded": True}})
    monkeypatch.setattr(cli, "cmd_setup", lambda args: calls.append("setup"))
    monkeypatch.setattr(cli, "cmd_home", lambda args: calls.append("home"))
    cli.main(["--tour"])
    assert calls == ["setup"]


def test_home_uses_arrow_select(monkeypatch, capsys):
    import cyrrus.cli as cli
    from cyrrus.ui.caps import Caps

    keys = iter(["DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "DOWN", "ENTER"])
    monkeypatch.setattr(cli, "load_config", lambda **kw: {"provider": {}, "memory": {}, "context": {}, "gateway": {}})
    monkeypatch.setattr("cyrrus.ui.caps.detect_caps", lambda: Caps(is_tty=True))
    monkeypatch.setattr("cyrrus.ui.widgets.UI._read_key", staticmethod(lambda: next(keys)))
    cli.cmd_home(type("Args", (), {"config": None})())
    assert "cyrrus home menu" in capsys.readouterr().out

# ---------------------------------------------------------------------------
# Existing file not overwritten without confirmation / --force
# ---------------------------------------------------------------------------

def test_existing_file_not_overwritten_without_confirmation(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cyrrus.config.json").write_text("EXISTING\n")
    # save="y", overwrite confirm="n", scope=""
    inputs = list(_NUMBERED_SCRIPT[:-1]) + ["n", ""]
    ui = ScriptedUI(inputs=inputs)
    result = run_setup(ui, non_interactive=False, plain=True, force=False)
    assert not result.get("cancelled")
    assert (tmp_path / "cyrrus.config.json").read_text() == "EXISTING\n"


def test_existing_file_overwritten_with_force(tmp_path, monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cyrrus.config.json").write_text("EXISTING\n")
    ui = ScriptedUI(inputs=list(_NUMBERED_SCRIPT))
    result = run_setup(ui, non_interactive=False, plain=True, force=True)
    assert not result.get("cancelled")
    assert (tmp_path / "cyrrus.config.json").read_text() != "EXISTING\n"
