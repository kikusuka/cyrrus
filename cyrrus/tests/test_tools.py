"""
Tests for the tools module.
"""
import copy
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
from cyrrus.memory import MemoryVault
import asyncio


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
    """Test memory-related functions."""

    def test_memory_list_empty(self, tmp_path):
        """Test memory_list returns empty list for new session."""
        db_path = str(tmp_path / "test_mem.db")
        result = memory_list(session="s1", db_path=db_path)
        assert result["success"] is True
        assert result["facts"] == []
        assert result["error"] is None

    def test_memory_list_with_data(self, tmp_path):
        """Test memory_list returns stored facts."""
        db_path = str(tmp_path / "test_mem.db")
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("s1", "user_name", "Alice", 1))
        result = memory_list(session="s1", db_path=db_path)
        assert result["success"] is True
        assert len(result["facts"]) == 1
        assert result["facts"][0]["key"] == "user_name"
        assert result["facts"][0]["value"] == "Alice"

    def test_memory_search(self, tmp_path):
        """Test memory_search retrieves matching facts."""
        db_path = str(tmp_path / "test_mem.db")
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("s1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("s1", "user_city", "Lisbon", 1))
        result = memory_search(session="s1", query="Alice", db_path=db_path)
        assert result["success"] is True
        assert len(result["results"]) >= 1
        assert result["results"][0]["key"] == "user_name"
        assert result["results"][0]["value"] == "Alice"
        assert "score" in result["results"][0]

    def test_memory_forget(self, tmp_path):
        """Test memory_forget deletes a fact."""
        db_path = str(tmp_path / "test_mem.db")
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("s1", "user_name", "Alice", 1))
        result = memory_forget(session="s1", key="user_name", db_path=db_path)
        assert result["success"] is True
        assert result["deleted"] is True
        remaining = memory_list(session="s1", db_path=db_path)
        assert len(remaining["facts"]) == 0

    def test_memory_forget_all(self, tmp_path):
        """Test memory_forget_all deletes all facts for session."""
        db_path = str(tmp_path / "test_mem.db")
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("s1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("s1", "user_city", "Lisbon", 1))
        result = memory_forget_all(session="s1", db_path=db_path)
        assert result["success"] is True
        assert result["count"] == 2
        remaining = memory_list(session="s1", db_path=db_path)
        assert len(remaining["facts"]) == 0

    def test_memory_export(self, tmp_path):
        """Test memory_export exports facts to JSON file."""
        db_path = str(tmp_path / "test_mem.db")
        out_file = tmp_path / "export.json"
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("s1", "user_name", "Alice", 1))
        result = memory_export(session="s1", path=str(out_file), db_path=db_path)
        assert result["success"] is True
        assert out_file.exists()
        assert result["count"] == 1
        with open(out_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["key"] == "user_name"

    def test_memory_import(self, tmp_path):
        """Test memory_import imports facts from JSON file."""
        db_path = str(tmp_path / "test_mem.db")
        in_file = tmp_path / "import.json"
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump([{"key": "user_name", "value": "Alice"}], f)
        result = memory_import(session="s1", path=str(in_file), db_path=db_path)
        assert result["success"] is True
        assert result["count"] == 1
        facts = memory_list(session="s1", db_path=db_path)
        assert len(facts["facts"]) == 1
        assert facts["facts"][0]["key"] == "user_name"
        assert facts["facts"][0]["value"] == "Alice"


class TestSessions:
    """Test sessions function."""

    def test_sessions_list(self, tmp_path):
        """Test sessions returns active fact counts across sessions."""
        db_path = str(tmp_path / "test_sessions.db")
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("sess1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("sess1", "user_city", "Lisbon", 1))
        asyncio.run(vault.upsert("sess2", "user_name", "Bob", 1))
        result = sessions(db_path=db_path)
        assert result["success"] is True
        assert len(result["sessions"]) == 2
        counts = {s["session_id"]: s.get("active_facts", s.get("fact_count", 0)) for s in result["sessions"]}
        assert counts["sess1"] == 2
        assert counts["sess2"] == 1


class TestBuildProjector:
    """Test build_projector function."""

    def test_build_projector_success(self):
        """Test building projector config."""
        config = copy.deepcopy(DEFAULTS)
        config["provider"]["service"] = "ollama"
        config["provider"]["model"] = "llama3.2"
        result = build_projector(config)
        assert result["success"] is True
        assert result["projector_config"]["service"] == "ollama"
        assert result["projector_config"]["model"] == "llama3.2"
