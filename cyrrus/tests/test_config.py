"""
Tests for the configuration system.
"""
import json
import os
import tempfile
from pathlib import Path
import pytest

from cyrrus.config import (
    get_user_config_dir,
    get_user_config_path,
    get_project_config_path,
    load_config_file,
    save_config_file,
    validate_config,
    load_config,
    save_project_config,
    save_user_config,
    load_dotenv,
    update_dotenv,
    redact_secrets,
    DEFAULTS,
    _deep_merge,
)


class TestConfigPaths:
    """Test configuration path resolution."""

    def test_get_user_config_dir_exists(self):
        """Test that user config directory is created."""
        path = get_user_config_dir()
        assert path.exists()
        assert path.is_dir()

    def test_get_user_config_path(self):
        """Test user config file path."""
        path = get_user_config_path()
        assert path.name == "cyrrus.config.json"
        assert path.parent == get_user_config_dir()

    def test_get_project_config_path_default(self):
        """Test project config path with default directory."""
        path = get_project_config_path()
        assert path.name == "cyrrus.config.json"
        assert path.parent == Path.cwd()

    def test_get_project_config_path_custom(self):
        """Test project config path with custom directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_project_config_path(Path(tmpdir))
            assert path.name == "cyrrus.config.json"
            assert path.parent == Path(tmpdir)


class TestConfigFileIO:
    """Test config file loading and saving."""

    def test_load_config_file_nonexistent(self):
        """Test loading a nonexistent file returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            result = load_config_file(path)
            assert result is None

    def test_load_config_file_valid(self):
        """Test loading a valid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            test_config = {"key": "value"}
            with open(path, "w") as f:
                json.dump(test_config, f)
            result = load_config_file(path)
            assert result == test_config

    def test_load_config_file_invalid_json(self):
        """Test loading invalid JSON raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            with open(path, "w") as f:
                f.write("not valid json")
            with pytest.raises(ValueError, match="Failed to load"):
                load_config_file(path)

    def test_save_config_file(self):
        """Test saving a config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            test_config = {"key": "value"}
            save_config_file(test_config, path)
            assert path.exists()
            with open(path) as f:
                loaded = json.load(f)
            assert loaded == test_config

    def test_save_config_file_creates_dir(self):
        """Test saving creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "config.json"
            test_config = {"key": "value"}
            save_config_file(test_config, path)
            assert path.exists()


class TestValidateConfig:
    """Test config validation."""

    def test_validate_config_defaults(self):
        """Test that DEFAULTS is valid."""
        result = validate_config(DEFAULTS.copy())
        assert result == DEFAULTS

    def test_validate_config_empty(self):
        """Test validating empty config fills with defaults."""
        result = validate_config({})
        assert "schema_version" in result
        assert "provider" in result
        assert "memory" in result
        assert "context" in result
        assert "ui" in result

    def test_validate_config_invalid_type(self):
        """Test that non-dict config raises ValueError."""
        with pytest.raises(ValueError, match="must be a dict"):
            validate_config("not a dict")

    def test_validate_config_schema_version(self):
        """Test schema_version validation."""
        config = DEFAULTS.copy()
        config["schema_version"] = "invalid"
        with pytest.raises(ValueError, match="must be an integer"):
            validate_config(config)

    def test_validate_config_provider_invalid_service(self):
        """Test provider.service type validation."""
        config = DEFAULTS.copy()
        config["provider"]["service"] = 123
        with pytest.raises(ValueError, match="provider.service must be a string"):
            validate_config(config)

    def test_validate_config_memory_invalid_retrieval(self):
        """Test memory.retrieval validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "invalid"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        with pytest.raises(ValueError, match="must be 'keyword' or 'hybrid'"):
            validate_config(config)

    def test_validate_config_memory_invalid_max_facts(self):
        """Test memory.max_facts_per_session validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"max_facts_per_session": -1},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        with pytest.raises(ValueError, match="must be a non-negative integer"):
            validate_config(config)

    def test_validate_config_memory_invalid_embedding_score(self):
        """Test memory.embedding_min_score validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"embedding_min_score": 1.5},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        with pytest.raises(ValueError, match="must be a number between 0 and 1"):
            validate_config(config)

    def test_validate_config_context_invalid_renderer(self):
        """Test context.renderer validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "invalid", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": False},
        }
        with pytest.raises(ValueError, match="must be 'default' or 'compact'"):
            validate_config(config)

    def test_validate_config_ui_invalid_animation(self):
        """Test ui.animation validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "invalid", "onboarded": False},
        }
        with pytest.raises(ValueError, match="must be 'auto' or 'off'"):
            validate_config(config)

    def test_validate_config_ui_invalid_onboarded(self):
        """Test ui.onboarded validation."""
        config = {
            "schema_version": 1,
            "provider": {"service": None, "base_url": None, "model": None, "api_key_env": None},
            "memory": {"retrieval": "keyword"},
            "context": {"renderer": "default", "max_context_tokens": 4000, "slides_path": "slides.json"},
            "ui": {"animation": "auto", "onboarded": "invalid"},
        }
        with pytest.raises(ValueError, match="must be a boolean"):
            validate_config(config)


class TestLoadConfig:
    """Test config loading with precedence."""

    def test_deep_merge(self):
        """Test _deep_merge helper."""
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}, "e": 4}
        result = _deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"]["c"] == 2
        assert result["b"]["d"] == 3
        assert result["e"] == 4


class TestSaveConfig:
    """Test config saving."""

    def test_save_project_config(self, tmp_path):
        """Test saving project config."""
        config = {"provider": {"service": "ollama"}}
        save_project_config(config, tmp_path)
        path = tmp_path / "cyrrus.config.json"
        assert path.exists()
        with open(path) as f:
            loaded = json.load(f)
        # Validation merges with defaults
        assert loaded["provider"]["service"] == "ollama"
        assert "schema_version" in loaded


class TestDotenv:
    """Test .env file handling."""

    def test_load_dotenv_nonexistent(self, tmp_path):
        """Test loading nonexistent .env returns empty dict."""
        result = load_dotenv(path=tmp_path / ".env")
        assert result == {}

    def test_load_dotenv_valid(self, tmp_path):
        """Test loading a valid .env file."""
        dotenv_path = tmp_path / ".env"
        with open(dotenv_path, "w") as f:
            f.write('KEY1=value1\nKEY2="value2"\n# comment\nKEY3=value3\n')

        result = load_dotenv(path=dotenv_path)
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"
        assert result["KEY3"] == "value3"

    def test_load_dotenv_no_override(self, tmp_path, monkeypatch):
        """Test that .env doesn't override existing env vars."""
        dotenv_path = tmp_path / ".env"
        with open(dotenv_path, "w") as f:
            f.write("KEY1=value1\n")

        monkeypatch.setenv("KEY1", "original")

        result = load_dotenv(path=dotenv_path)
        assert "KEY1" not in result  # Not loaded because it exists
        assert os.environ["KEY1"] == "original"

    def test_update_dotenv_new(self, tmp_path, monkeypatch):
        """Test updating .env with new key."""
        monkeypatch.chdir(tmp_path)
        update_dotenv("NEW_KEY", "new_value", path=tmp_path / ".env")
        dotenv_path = tmp_path / ".env"
        assert dotenv_path.exists()
        with open(dotenv_path) as f:
            content = f.read()
        assert "NEW_KEY=new_value" in content

    def test_update_dotenv_existing(self, tmp_path, monkeypatch):
        """Test updating .env updates existing key."""
        dotenv_path = tmp_path / ".env"
        with open(dotenv_path, "w") as f:
            f.write("KEY1=old_value\n")

        monkeypatch.chdir(tmp_path)
        update_dotenv("KEY1", "new_value", path=dotenv_path)
        with open(dotenv_path) as f:
            content = f.read()
        assert "KEY1=new_value" in content
        assert "old_value" not in content

    def test_update_dotenv_gitignore(self, tmp_path, monkeypatch):
        """Test that update_dotenv adds .env to .gitignore."""
        monkeypatch.chdir(tmp_path)
        update_dotenv("KEY1", "value1", path=tmp_path / ".env")
        gitignore_path = tmp_path / ".gitignore"
        assert gitignore_path.exists()
        with open(gitignore_path) as f:
            content = f.read()
        assert ".env" in content


class TestRedactSecrets:
    """Test secret redaction."""

    def test_redact_secrets_api_key_env(self):
        """Test that api_key_env is redacted."""
        config = {
            "provider": {
                "api_key_env": "OPENAI_API_KEY"
            }
        }
        result = redact_secrets(config)
        assert result["provider"]["api_key_env"] == "*****"

    def test_redact_secrets_none_key(self):
        """Test that None api_key_env is not redacted."""
        config = {
            "provider": {
                "api_key_env": None
            }
        }
        result = redact_secrets(config)
        assert result["provider"]["api_key_env"] is None

    def test_redact_secrets_no_provider(self):
        """Test that config without provider is handled."""
        config = {"memory": {"db_path": "test.db"}}
        result = redact_secrets(config)
        assert result == config
