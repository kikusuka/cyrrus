"""
Real SQLite tests for CLI memory and sessions commands.
Testing through main(argv) with temporary database and configuration.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import pytest

from cyrrus.cli import main
from cyrrus.memory import MemoryVault
from cyrrus.extractor import extract_facts


@pytest.fixture
def temp_env(tmp_path):
    """Create a temporary database and configuration directory."""
    db_path = str(tmp_path / "test_memory.db")
    config_dir = tmp_path
    config_path = config_dir / "cyrrus.config.json"
    config_data = {
        "schema_version": 1,
        "provider": {},
        "memory": {"db_path": db_path},
        "context": {},
        "ui": {},
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f)
    return {"db_path": db_path, "config_dir": str(config_dir), "tmp_path": tmp_path}


class TestCLIMemoryAndSessions:
    """Test suite for memory and sessions CLI commands with real SQLite."""

    def test_regression_memory_list_returns_facts(self, temp_env, capsys):
        """Regression test proving memory list on a database containing facts returns them."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        # Store facts via MemoryVault
        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("user1", "user_city", "Lisbon", 1))

        # Test --json output
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert len(data["facts"]) == 2
        keys = {f["key"] for f in data["facts"]}
        assert keys == {"user_name", "user_city"}

        # Test human-readable text output
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "memory", "list"])
        captured_text = capsys.readouterr()
        assert "Facts (2):" in captured_text.out
        assert "[user_name] Alice" in captured_text.out
        assert "[user_city] Lisbon" in captured_text.out

    def test_superseded_facts_hidden_by_default_and_shown_with_flag(self, temp_env, capsys):
        """Superseded facts are hidden by default and shown with --include-superseded flag."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_city", "Paris", 1))
        asyncio.run(vault.upsert("user1", "user_city", "Lisbon", 1))  # supersedes Paris

        # Default list: hidden
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert len(data["facts"]) == 1
        assert data["facts"][0]["key"] == "user_city"
        assert data["facts"][0]["value"] == "Lisbon"
        assert data["facts"][0]["invalid_at"] is None

        # With flag: both shown
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list", "--include-superseded"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert len(data["facts"]) == 2
        assert data["facts"][0]["value"] == "Paris"
        assert data["facts"][0]["invalid_at"] is not None
        assert data["facts"][1]["value"] == "Lisbon"
        assert data["facts"][1]["invalid_at"] is None

    def test_memory_search(self, temp_env, capsys):
        """Test searching facts returns matching key, value, and score."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("user1", "user_city", "Lisbon", 1))

        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "search", "Lisbon"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert len(data["results"]) >= 1
        top = data["results"][0]
        assert top["key"] == "user_city"
        assert top["value"] == "Lisbon"
        assert "score" in top
        assert top["score"] > 0

    def test_memory_forget(self, temp_env, capsys):
        """Test memory forget deletes a specific fact."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("user1", "user_city", "Lisbon", 1))

        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "forget", "user_name", "--yes"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["deleted"] is True

        # Verify only user_city remains
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["facts"]) == 1
        assert data["facts"][0]["key"] == "user_city"

    def test_memory_forget_all_refused_without_yes(self, temp_env, capsys):
        """Test forget-all is refused when --yes is omitted in non-interactive environment."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_name", "Alice", 1))

        with pytest.raises(SystemExit) as exc:
            main(["--config", config_dir, "--db", db_path, "--session", "user1", "memory", "forget-all"])
        assert exc.value.code == 1

        # Verify fact was NOT deleted
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["facts"]) == 1

    def test_memory_forget_all_with_yes(self, temp_env, capsys):
        """Test forget-all deletes all facts when --yes is supplied."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("user1", "user_name", "Alice", 1))
        asyncio.run(vault.upsert("user1", "user_city", "Lisbon", 1))

        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "forget-all", "--yes"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["count"] == 2

        # Verify list is empty
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data["facts"]) == 0

    def test_round_trip_export_forget_import(self, temp_env, capsys):
        """Round trip test: export, forget-all, import, then list equals original."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]
        tmp_path = temp_env["tmp_path"]

        # Store facts via extractor/vault
        vault = MemoryVault(db_path=db_path)
        extracted = asyncio.run(extract_facts("My name is Alice and I work at Anthropic"))
        for k, v in extracted.items():
            asyncio.run(vault.upsert("user1", k, v, 2))

        # 1. List original
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        orig_data = json.loads(capsys.readouterr().out)
        assert len(orig_data["facts"]) >= 1

        # 2. Export
        export_file = str(tmp_path / "roundtrip.json")
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "export", "--file", export_file])
        export_res = json.loads(capsys.readouterr().out)
        assert export_res["success"] is True
        assert Path(export_file).exists()

        # 3. Forget all
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "forget-all", "--yes"])
        capsys.readouterr()

        # Verify empty
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        empty_data = json.loads(capsys.readouterr().out)
        assert len(empty_data["facts"]) == 0

        # 4. Import
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "import", "--file", export_file])
        import_res = json.loads(capsys.readouterr().out)
        assert import_res["success"] is True
        assert import_res["count"] == len(orig_data["facts"])

        # 5. List after import
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        new_data = json.loads(capsys.readouterr().out)

        orig_pairs = sorted([(f["key"], f["value"]) for f in orig_data["facts"]])
        new_pairs = sorted([(f["key"], f["value"]) for f in new_data["facts"]])
        assert orig_pairs == new_pairs

    def test_sessions_counts_for_two_sessions(self, temp_env, capsys):
        """Test sessions command returns session IDs with active fact counts."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]

        vault = MemoryVault(db_path=db_path)
        asyncio.run(vault.upsert("sess_alpha", "fact1", "val1", 1))
        asyncio.run(vault.upsert("sess_alpha", "fact2", "val2", 1))
        asyncio.run(vault.upsert("sess_beta", "fact3", "val3", 1))

        main(["--config", config_dir, "--db", db_path, "--json", "sessions"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert len(data["sessions"]) == 2

        session_map = {
            s["session_id"]: s.get("active_facts", s.get("fact_count", 0))
            for s in data["sessions"]
        }
        assert session_map["sess_alpha"] == 2
        assert session_map["sess_beta"] == 1

        # Text output test
        main(["--config", config_dir, "--db", db_path, "sessions"])
        captured_text = capsys.readouterr()
        assert "Sessions (2):" in captured_text.out
        assert "[sess_alpha] (2 active facts)" in captured_text.out
        assert "[sess_beta] (1 active facts)" in captured_text.out

    def test_invalid_import_file_rejected(self, temp_env, capsys):
        """Invalid import file is rejected with a clear error without partial writes."""
        db_path = temp_env["db_path"]
        config_dir = temp_env["config_dir"]
        tmp_path = temp_env["tmp_path"]

        # Bad file where one row has an overly long key (>256 chars)
        bad_file = tmp_path / "bad_import.json"
        bad_data = [
            {"key": "valid_key", "value": "valid_val"},
            {"key": "x" * 300, "value": "too long key"},
        ]
        with open(bad_file, "w", encoding="utf-8") as f:
            json.dump(bad_data, f)

        with pytest.raises(SystemExit):
            main(["--config", config_dir, "--db", db_path, "--session", "user1", "memory", "import", "--file", str(bad_file)])

        captured = capsys.readouterr()
        assert "key too long" in captured.err or "Error:" in captured.err

        # Ensure NO facts were stored (no partial import)
        main(["--config", config_dir, "--db", db_path, "--session", "user1", "--json", "memory", "list"])
        data = json.loads(capsys.readouterr().out)
        assert len(data["facts"]) == 0
