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
