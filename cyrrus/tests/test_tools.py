"""
Tests for the tools module.
"""
import json
import tempfile
from pathlib import Path
import pytest

from cyrrus.tools import (
    list_models,
    check_connection,
    doctor,
    route_dry_run,
    memory_list,
    memory_search,
    memory_forget,
    memory_forget_all,
    memory_export,
    memory_import,
    sessions,
    build_projector,
)
from cyrrus.config import DEFAULTS


class TestListModels:
    """Test list_models function."""

    def test_list_models_unknown_service(self):
        """Test listing models for unknown service."""
        result = list_models("unknown_service")
        assert result["success"] is False
        assert result["models"] == []
        assert "Unknown service" in result["error"]

    def test_list_models_ollama_no_server(self):
        """Test listing Ollama models when server not running."""
        result = list_models("ollama", timeout=0.5)
        # Server might or might not be running, just check structure
        assert "success" in result
        assert "models" in result
        assert isinstance(result["models"], list)


class TestConnectionCheck:
    """Test check_connection function."""

    def test_connection_no_service(self):
        """Test connection with no service configured."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        result = check_connection(config)
        assert result["success"] is False
        assert result["reachable"] is False
        assert "No service configured" in result["error"]

    def test_connection_unknown_service(self):
        """Test connection with unknown service."""
        config = {
            "schema_version": 1,
            "provider": {"service": "unknown", "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        result = check_connection(config)
        assert result["success"] is False
        assert result["reachable"] is False
        assert "Unknown service" in result["error"]

    def test_connection_no_model(self):
        """Test connection with service but no model."""
        config = {
            "schema_version": 1,
            "provider": {"service": "ollama", "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        result = check_connection(config)
        # Ollama likely not running, so reachable will be False
        assert result["completion_ok"] is False


class TestDoctor:
    """Test doctor function."""

    def test_doctor_with_valid_config(self):
        """Test doctor with valid configuration."""
        config = DEFAULTS.copy()
        result = doctor(config)
        assert "overall_status" in result
        assert "checks" in result
        assert isinstance(result["checks"], list)
        assert len(result["checks"]) > 0

    def test_doctor_config_load_error(self, monkeypatch):
        """Test doctor when config load fails."""
        def mock_load(*args, **kwargs):
            raise Exception("Config load failed")

        monkeypatch.setattr("cyrrus.tools.load_config", mock_load)
        result = doctor()
        assert result["overall_status"] == "error"
        assert len(result["checks"]) == 1
        assert result["checks"][0]["name"] == "config_load"
        assert result["checks"][0]["status"] == "error"


class TestRouteDryRun:
    """Test route_dry_run function."""

    def test_route_dry_run_missing_file(self):
        """Test dry run with missing slides file."""
        result = route_dry_run("test text", slides_path="/nonexistent/slides.json")
        assert result["success"] is False
        assert result["selected_slides"] == []
        assert "not found" in result["error"]

    def test_route_dry_run_valid_file(self, tmp_path):
        """Test dry run with valid slides file."""
        slides_path = tmp_path / "slides.json"
        slides = {
            "core_lamp": {"content": "You are helpful."},
            "code_lens": {
                "content": "Output code.",
                "triggers": ["code", "script"],
            },
        }
        with open(slides_path, "w") as f:
            json.dump(slides, f)

        result = route_dry_run("write some code", str(slides_path))
        assert result["success"] is True
        assert "core_lamp" in result["selected_slides"]
        assert "code_lens" in result["selected_slides"]

    def test_route_dry_run_no_match(self, tmp_path):
        """Test dry run with no matching triggers."""
        slides_path = tmp_path / "slides.json"
        slides = {
            "core_lamp": {"content": "You are helpful."},
            "code_lens": {
                "content": "Output code.",
                "triggers": ["code", "script"],
            },
        }
        with open(slides_path, "w") as f:
            json.dump(slides, f)

        result = route_dry_run("hello world", str(slides_path))
        assert result["success"] is True
        assert result["selected_slides"] == ["core_lamp"]


class TestMemoryFunctions:
    """Test memory-related functions (placeholders)."""

    def test_memory_list_placeholder(self):
        """Test memory_list returns placeholder."""
        result = memory_list()
        assert result["success"] is False
        assert result["facts"] == []
        assert "not yet implemented" in result["error"]

    def test_memory_search_placeholder(self):
        """Test memory_search returns placeholder."""
        result = memory_search("test query")
        assert result["success"] is False
        assert result["results"] == []
        assert "not yet implemented" in result["error"]

    def test_memory_forget_placeholder(self):
        """Test memory_forget returns placeholder."""
        result = memory_forget(1)
        assert result["success"] is False
        assert result["deleted"] is False
        assert "not yet implemented" in result["error"]

    def test_memory_forget_all_placeholder(self):
        """Test memory_forget_all returns placeholder."""
        result = memory_forget_all()
        assert result["success"] is False
        assert result["count"] == 0
        assert "not yet implemented" in result["error"]

    def test_memory_export_placeholder(self):
        """Test memory_export returns placeholder."""
        result = memory_export()
        assert result["success"] is False
        assert result["output_path"] is None
        assert result["count"] == 0
        assert "not yet implemented" in result["error"]

    def test_memory_import_placeholder(self):
        """Test memory_import returns placeholder."""
        result = memory_import("/path/to/file.json")
        assert result["success"] is False
        assert result["count"] == 0
        assert "not yet implemented" in result["error"]


class TestSessions:
    """Test sessions function (placeholder)."""

    def test_sessions_placeholder(self):
        """Test sessions returns placeholder."""
        result = sessions()
        assert result["success"] is False
        assert result["sessions"] == []
        assert "not yet implemented" in result["error"]


class TestBuildProjector:
    """Test build_projector function."""

    def test_build_projector_success(self):
        """Test building projector config."""
        config = DEFAULTS.copy()
        config["provider"]["service"] = "ollama"
        config["provider"]["model"] = "llama3.2"
        result = build_projector(config)
        assert result["success"] is True
        assert result["projector_config"]["service"] == "ollama"
        assert result["projector_config"]["model"] == "llama3.2"
