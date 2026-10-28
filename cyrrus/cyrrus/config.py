"""
Configuration system for Cyrrus.

Manages project and user settings files with proper precedence:
command-line flags > environment variables > project file > user file > defaults.
"""
import json
import os
import sys
from typing import Dict, Any, Optional, List
from pathlib import Path


# Default configuration values
DEFAULTS = {
    "schema_version": 1,
    "provider": {
        "service": None,
        "base_url": None,
        "model": None,
        "api_key_env": None,
    },
    "memory": {
        "db_path": None,  # Will use default_db_path() if None
        "retrieval": "keyword",  # "keyword" or "hybrid"
        "max_facts_per_session": 50,
        "embedding_min_score": 0.7,
    },
    "context": {
        "renderer": "default",  # "default" or "compact"
        "max_context_tokens": 4000,
        "slides_path": "slides.json",
    },
    "ui": {
        "animation": "auto",  # "auto" or "off"
        "onboarded": False,
    },
}


def get_user_config_dir() -> Path:
    """
    Get the per-user configuration directory.

    Windows: %LOCALAPPDATA%\\cyrrus\\ (or ~\\cyrrus if LOCALAPPDATA missing)
    macOS/Linux: $XDG_DATA_HOME/cyrrus/ or ~/.local/share/cyrrus/

    The directory is created if it doesn't exist.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        folder = Path(base) / "cyrrus"
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        folder = Path(base) / "cyrrus"

    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_user_config_path() -> Path:
    """Get the path to the per-user settings file."""
    return get_user_config_dir() / "cyrrus.config.json"


def get_project_config_path(project_dir: Optional[Path] = None) -> Path:
    """
    Get the path to the project settings file.

    Args:
        project_dir: Project directory. If None, uses current working directory.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    return Path(project_dir) / "cyrrus.config.json"


def load_config_file(path: Path) -> Optional[Dict[str, Any]]:
    """
    Load a JSON config file. Returns None if file doesn't exist.

    Args:
        path: Path to the config file.

    Returns:
        Parsed config as dict, or None if file doesn't exist.
    """
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Failed to load config from {path}: {e}")


def save_config_file(config: Dict[str, Any], path: Path) -> None:
    """
    Save a config dict to a JSON file.

    Args:
        config: Configuration dictionary.
        path: Path to save the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize a config dict.

    Ensures all required top-level keys exist and have correct types.
    Fills in missing values from DEFAULTS.

    Args:
        config: Configuration dictionary to validate.

    Returns:
        Normalized configuration dictionary.

    Raises:
        ValueError: If config has invalid structure or values.
    """
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a dict, got {type(config).__name__}")

    # Start with defaults and overlay the provided config
    normalized = _deep_merge(DEFAULTS.copy(), config)

    # Validate schema_version
    if "schema_version" not in normalized:
        normalized["schema_version"] = 1
    elif not isinstance(normalized["schema_version"], int):
        raise ValueError("schema_version must be an integer")

    # Validate provider section
    if "provider" in normalized:
        provider = normalized["provider"]
        if not isinstance(provider, dict):
            raise ValueError("provider must be a dict")
        if "service" in provider and provider["service"] is not None:
            if not isinstance(provider["service"], str):
                raise ValueError("provider.service must be a string or null")
        if "base_url" in provider and provider["base_url"] is not None:
            if not isinstance(provider["base_url"], str):
                raise ValueError("provider.base_url must be a string or null")
        if "model" in provider and provider["model"] is not None:
            if not isinstance(provider["model"], str):
                raise ValueError("provider.model must be a string or null")
        if "api_key_env" in provider and provider["api_key_env"] is not None:
            if not isinstance(provider["api_key_env"], str):
                raise ValueError("provider.api_key_env must be a string or null")

    # Validate memory section
    if "memory" in normalized:
        memory = normalized["memory"]
        if not isinstance(memory, dict):
            raise ValueError("memory must be a dict")
        if memory.get("retrieval") not in (None, "keyword", "hybrid"):
            raise ValueError("memory.retrieval must be 'keyword' or 'hybrid'")
        if "max_facts_per_session" in memory and memory["max_facts_per_session"] is not None:
            if not isinstance(memory["max_facts_per_session"], int) or memory["max_facts_per_session"] < 0:
                raise ValueError("memory.max_facts_per_session must be a non-negative integer")
        if "embedding_min_score" in memory and memory["embedding_min_score"] is not None:
            if not isinstance(memory["embedding_min_score"], (int, float)) or not (0 <= memory["embedding_min_score"] <= 1):
                raise ValueError("memory.embedding_min_score must be a number between 0 and 1")

    # Validate context section
    if "context" in normalized:
        context = normalized["context"]
        if not isinstance(context, dict):
            raise ValueError("context must be a dict")
        if context.get("renderer") not in (None, "default", "compact"):
            raise ValueError("context.renderer must be 'default' or 'compact'")
        if "max_context_tokens" in context and context["max_context_tokens"] is not None:
            if not isinstance(context["max_context_tokens"], int) or context["max_context_tokens"] < 0:
                raise ValueError("context.max_context_tokens must be a non-negative integer")

    # Validate ui section
    if "ui" in normalized:
        ui = normalized["ui"]
        if not isinstance(ui, dict):
            raise ValueError("ui must be a dict")
        if ui.get("animation") not in (None, "auto", "off"):
            raise ValueError("ui.animation must be 'auto' or 'off'")
        if "onboarded" in ui and ui["onboarded"] is not None:
            if not isinstance(ui["onboarded"], bool):
                raise ValueError("ui.onboarded must be a boolean")

    return normalized


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries. Values from override take precedence.

    Args:
        base: Base dictionary.
        override: Dictionary with override values.

    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    project_dir: Optional[Path] = None,
    env_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Load configuration with proper precedence.

    Precedence: env_overrides > project file > user file > defaults.

    Args:
        project_dir: Project directory. If None, uses current working directory.
        env_overrides: Dictionary of environment variable overrides.
                       Keys are dotted paths like "provider.service".

    Returns:
        Normalized configuration dictionary.
    """
    # Start with defaults
    config = DEFAULTS.copy()

    # Apply user file
    user_config = load_config_file(get_user_config_path())
    if user_config:
        config = _deep_merge(config, user_config)

    # Apply project file
    project_config = load_config_file(get_project_config_path(project_dir))
    if project_config:
        config = _deep_merge(config, project_config)

    # Apply environment overrides
    if env_overrides:
        for key_path, value in env_overrides.items():
            _set_dotted_key(config, key_path, value)

    # Validate and normalize
    return validate_config(config)


def _set_dotted_key(config: Dict[str, Any], key_path: str, value: str) -> None:
    """
    Set a value in a nested dict using a dotted key path.

    Args:
        config: Configuration dictionary to modify.
        key_path: Dotted path like "provider.service".
        value: Value to set (as string, will be converted if needed).
    """
    keys = key_path.split(".")
    current = config

    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Convert value to appropriate type (only for boolean-like values)
    final_key = keys[-1]
    if value.lower() == "true":
        current[final_key] = True
    elif value.lower() == "false":
        current[final_key] = False
    else:
        current[final_key] = value


def save_project_config(config: Dict[str, Any], project_dir: Optional[Path] = None) -> None:
    """
    Save configuration to the project settings file.

    Args:
        config: Configuration dictionary to save.
        project_dir: Project directory. If None, uses current working directory.
    """
    validated = validate_config(config)
    save_config_file(validated, get_project_config_path(project_dir))


def save_user_config(config: Dict[str, Any]) -> None:
    """
    Save configuration to the user settings file.

    Args:
        config: Configuration dictionary to save.
    """
    validated = validate_config(config)
    save_config_file(validated, get_user_config_path())


def load_dotenv(path: Optional[Path] = None) -> Dict[str, str]:
    """
    Load a .env file without overriding existing environment variables.

    Args:
        path: Path to .env file. If None, looks for .env in current directory.

    Returns:
        Dictionary of loaded environment variables.
    """
    if path is None:
        path = Path.cwd() / ".env"

    if not path.exists():
        return {}

    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    # Only add if not already in environment
                    if key not in os.environ:
                        result[key] = value
    except OSError:
        pass

    return result


def update_dotenv(key: str, value: str, path: Optional[Path] = None) -> None:
    """
    Update or add a key in a .env file.

    Ensures .env is listed in .gitignore (creates it if missing).

    Args:
        key: Environment variable name.
        value: Value to set.
        path: Path to .env file. If None, uses .env in current directory.
    """
    if path is None:
        path = Path.cwd() / ".env"

    # Ensure .gitignore exists and contains .env
    gitignore_path = Path.cwd() / ".gitignore"
    gitignore_lines = []
    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8") as f:
            gitignore_lines = f.read().splitlines()

    if ".env" not in gitignore_lines:
        with open(gitignore_path, "a", encoding="utf-8") as f:
            if gitignore_lines and not gitignore_lines[-1]:
                f.write("\n")
            f.write(".env\n")

    # Read existing .env content
    existing_lines = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing_lines = f.read().splitlines()

    # Update or add the key
    updated_lines = []
    key_found = False
    for line in existing_lines:
        if line.strip().startswith(f"{key}="):
            updated_lines.append(f"{key}={value}")
            key_found = True
        else:
            updated_lines.append(line)

    if not key_found:
        updated_lines.append(f"{key}={value}")

    # Write back
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(updated_lines))
        if updated_lines and not updated_lines[-1].endswith("\n"):
            f.write("\n")


def redact_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of config with secrets redacted.

    Redacts API keys and other sensitive values.

    Args:
        config: Configuration dictionary.

    Returns:
        Configuration dictionary with secrets replaced by "*****".
    """
    result = json.loads(json.dumps(config))  # Deep copy

    # Redact api_key_env values (they point to env vars, not the keys themselves)
    if "provider" in result and isinstance(result["provider"], dict):
        if "api_key_env" in result["provider"] and result["provider"]["api_key_env"]:
            result["provider"]["api_key_env"] = "*****"

    return result
