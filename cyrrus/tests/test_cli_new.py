"""
Tests for new CLI commands (doctor, connect, services, models, route, memory, sessions, config).
"""
import json
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch

from cyrrus.cli import main


class TestCLIDoctor:
    """Test doctor command."""

    def test_cli_doctor_json(self, monkeypatch):
        """Test doctor command with JSON output."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {}})
        result = main(["--json", "doctor"])
        # Just check it doesn't crash
        assert result is None or result == 0

    def test_cli_doctor_json_trailing_flag(self, monkeypatch):
        """Test doctor accepts --json after the subcommand."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {}})
        result = main(["doctor", "--json"])
        assert result is None or result == 0

    def test_cli_doctor_text(self, monkeypatch):
        """Test doctor command with text output."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {}})
        result = main(["doctor"])
        assert result is None or result == 0


class TestCLIServices:
    """Test services command."""

    def test_cli_services_json(self, monkeypatch):
        """Test services command with JSON output."""
        monkeypatch.setattr("cyrrus.cli.detect_services", lambda timeout: {})
        result = main(["--json", "services"])
        assert result is None or result == 0

    def test_cli_services_json_trailing_flag(self, monkeypatch):
        """Test services accepts --json after the subcommand."""
        monkeypatch.setattr("cyrrus.cli.detect_services", lambda timeout: {})
        result = main(["services", "--json"])
        assert result is None or result == 0

    def test_cli_services_text(self, monkeypatch):
        """Test services command with text output."""
        monkeypatch.setattr("cyrrus.cli.detect_services", lambda timeout: {})
        result = main(["services"])
        assert result is None or result == 0


class TestCLIConfig:
    """Test config command."""

    def test_cli_config_show(self, monkeypatch):
        """Test config show command."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {}})
        result = main(["config", "show"])
        assert result is None or result == 0

    def test_cli_config_show_json_trailing_flag(self, monkeypatch):
        """Test config show accepts --json after the subcommand."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {}, "ui": {}})
        result = main(["config", "show", "--json"])
        assert result is None or result == 0

    def test_cli_config_path(self, monkeypatch):
        """Test config path command."""
        result = main(["config", "path"])
        assert result is None or result == 0


class TestCLIRoute:
    """Test route command."""

    def test_cli_route_valid(self, tmp_path, monkeypatch):
        """Test route command with valid slides file."""
        slides_path = tmp_path / "slides.json"
        slides = {
            "core_lamp": {"content": "You are helpful."},
            "code_lens": {
                "content": "Output code.",
                "triggers": ["code"],
            },
        }
        with open(slides_path, "w") as f:
            json.dump(slides, f)

        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {"slides_path": str(slides_path)}, "ui": {}})
        result = main(["route", "write some code"])
        assert result is None or result == 0

    def test_cli_route_missing_file(self, monkeypatch):
        """Test route command with missing slides file."""
        monkeypatch.setattr("cyrrus.cli.load_config", lambda **kw: {"schema_version": 1, "provider": {}, "memory": {}, "context": {"slides_path": "nonexistent.json"}, "ui": {}})
        with pytest.raises(SystemExit):
            main(["route", "test"])


class TestCLIInitExisting:
    """Test that existing init command still works."""

    def test_cli_init_non_interactive(self, tmp_path):
        """Test init command in non-interactive mode."""
        output = tmp_path / "slides.json"
        result = main(["init", "--template", "coding", "--tone", "professional", "--yes", "--output", str(output)])
        assert output.exists()
        assert result is None or result == 0

    def test_cli_no_command(self):
        """Test CLI with no command prints help."""
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 0


class TestCLISetupTestMessage:
    """Test the wizard's test-message flow (step 4)."""

    def _fake_upstream(self, tmp_path, monkeypatch):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        bodies = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.endswith("/models"):
                    data = b'{"object":"list","data":[{"id":"test-model"}]}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                bodies.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"Hello Alice!"}}]}')

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        return upstream, bodies

    def test_setup_test_message_uses_gateway_and_reports_injection(self, tmp_path, monkeypatch):
        """Non-dry scripted run with --test-message starts an in-process gateway on a
        free port against a fake upstream, sends one message, prints the reply and
        what Cyrrus injected, then stops the gateway."""
        import io
        from cyrrus.setup import run_setup
        from cyrrus.ui.widgets import UI
        from cyrrus.ui.caps import Caps

        upstream, bodies = self._fake_upstream(tmp_path, monkeypatch)
        upstream_base = "http://127.0.0.1:%d/v1" % upstream.server_address[1]
        try:
            monkeypatch.chdir(tmp_path)
            monkeypatch.setattr("cyrrus.setup.detect_services", lambda timeout: {})
            out = io.StringIO()
            ui = UI(output=out, caps=Caps(is_tty=False, unicode=False, width=80, height=24))
            overrides = {
                "goal": "gateway", "service": "custom", "base_url": upstream_base,
                "model": "test-model", "skip_test": True, "test_message": True,
                "memory_db": "project", "retrieval": "keyword", "renderer": "default",
                "starter_slide": "assistant", "scope": "project",
                "start_gateway": False, "yes": True,
            }
            result = run_setup(
                ui, non_interactive=True, dry_run=False, plain=True, force=True,
                overrides=overrides,
            )
            assert not result["cancelled"]
            assert result["test_message"] is True
            assert result["start_gateway"] is False

            assert bodies, "no request reached the upstream"
            messages = bodies[-1]["messages"]
            assert any(m.get("role") == "user" and "Alice" in m.get("content", "") for m in messages)
            # Cyrrus injects a system message (context) ahead of the user message.
            assert messages[0]["role"] == "system", messages
            output = out.getvalue()
            assert "reply:" in output, output
            assert "cyrrus injected facts" in output, output
        finally:
            upstream.shutdown()
            upstream.server_close()

    def test_setup_dry_run_offers_no_actions(self, tmp_path, monkeypatch):
        """Dry run ends with 'Dry run finished; nothing was written.' and offers
        neither the test-message nor the start-gateway action."""
        import io
        from cyrrus.setup import run_setup
        from cyrrus.ui.widgets import UI
        from cyrrus.ui.caps import Caps

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("cyrrus.setup.detect_services", lambda timeout: {})
        out = io.StringIO()
        ui = UI(output=out, caps=Caps(is_tty=False, width=80, height=24))
        overrides = {
            "goal": "gateway", "service": "custom", "base_url": "http://127.0.0.1:1/v1",
            "model": "test-model", "skip_test": True, "test_message": True,
            "memory_db": "project", "retrieval": "keyword", "renderer": "default",
            "starter_slide": "assistant", "scope": "project", "start_gateway": True,
            "yes": True,
        }
        result = run_setup(
            ui, non_interactive=True, dry_run=True, plain=True, force=True,
            overrides=overrides,
        )
        output = out.getvalue()
        assert "Dry run finished; nothing was written." in output
        assert result["test_message"] is False
        assert result["start_gateway"] is False
        assert result["written"] == []


class TestCLIHomeIntro:
    """Test home menu and intro polish (step 5)."""

    def test_home_menu_uses_panel_and_single_select(self, monkeypatch):
        """The status panel is rendered once via panel(); exactly one select() call
        (one way to choose) with each option appearing once."""
        import cyrrus.cli as cli
        import cyrrus.ui.widgets as widgets

        captured = {"panel_calls": 0, "select_calls": 0, "title": None, "options": None}

        class FakeUI:
            def __init__(self, caps=None):
                self.output = []
                self.caps = caps
            def write(self, text=""):
                self.output.append(text)

        fake_ui = FakeUI()

        def fake_panel(ui, title, lines):
            captured["panel_calls"] += 1
            captured["title"] = title
            captured["panel_lines"] = list(lines)

        def fake_select(ui, prompt, options, default=0):
            captured["select_calls"] += 1
            captured["options"] = list(options)
            return "quit"

        monkeypatch.setattr(widgets, "UI", lambda caps=None: fake_ui)
        monkeypatch.setattr(widgets, "panel", fake_panel)
        monkeypatch.setattr(widgets, "select", fake_select)
        monkeypatch.setattr(cli, "load_config", lambda **kw: {"gateway": {}, "provider": {}, "memory": {}, "context": {}})
        monkeypatch.setattr(cli, "detect_caps", lambda: object())
        monkeypatch.setattr(cli, "cmd_setup", lambda *a, **k: None)
        monkeypatch.setattr(cli, "cmd_doctor", lambda *a, **k: None)

        args = cli.build_parser().parse_args(["home"])
        cli.cmd_home(args)

        assert captured["panel_calls"] == 1, "panel should be rendered once"
        assert captured["title"] == "cyrrus home"
        assert captured["select_calls"] == 1, "exactly one select (one way to choose)"
        labels = [opt[0] for opt in captured["options"]]
        assert len(labels) == len(set(labels)), "each option appears once: %r" % labels

    def test_intro_ends_with_header_never_blank(self, monkeypatch):
        """`cyrrus intro` ends with the one-line header and never clears to a blank screen."""
        import io
        import cyrrus.cli as cli
        import cyrrus.ui.anim as anim

        played = {"clear_after": None}
        out = io.StringIO()

        def fake_play_intro(caps, out_stream, sleep, kbhit, mode, tier, clear_after):
            played["clear_after"] = clear_after
            out_stream.write("intro animation frames\n")

        monkeypatch.setattr(anim, "play_intro", fake_play_intro)
        monkeypatch.setattr(cli, "load_config", lambda **kw: {"ui": {"animation": "auto"}})
        monkeypatch.setattr(cli, "detect_caps", lambda: object())
        monkeypatch.setattr(cli, "should_animate", lambda *a, **k: True)
        monkeypatch.setattr(cli.sys, "stdout", out)

        args = cli.build_parser().parse_args(["intro"])
        cli.cmd_intro(args)

        assert played["clear_after"] is False, "intro must not clear the screen"
        assert out.getvalue().strip().endswith("cyrrus · by Breezy Labs"), out.getvalue()
