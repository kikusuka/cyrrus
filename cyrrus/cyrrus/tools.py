"""
Plain tool functions for Cyrrus.

All functions return data (dicts, lists, etc.) without printing.
Intended for use by CLI, menu interface, and MCP server.
"""
import json
import os
import socket
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from .services import get_service, detect_services
from .config import load_config, redact_secrets
from .sqlite_backend import default_db_path


def list_models(
    service_id: str,
    base_url: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    List available models for a service.

    Args:
        service_id: Service ID (e.g., "ollama", "lmstudio").
        base_url: Override base URL. If None, uses service default.
        timeout: Request timeout in seconds.

    Returns:
        Dict with keys:
        - success: bool
        - models: list of model names (if successful)
        - error: error message (if failed)
    """
    service = get_service(service_id)
    if not service:
        return {
            "success": False,
            "models": [],
            "error": f"Unknown service: {service_id}",
        }

    url = base_url or service.default_base_url
    if service.models_endpoint:
        endpoint = url.rstrip("/") + service.models_endpoint
    else:
        return {
            "success": False,
            "models": [],
            "error": f"Service {service_id} does not support model listing",
        }

    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            data = json.loads(body.decode("utf-8", errors="replace"))

            # Normalize response format based on service
            if service_id == "ollama":
                models = [m["name"] for m in data.get("models", [])]
            else:
                # OpenAI-compatible format
                models = [m["id"] for m in data.get("data", [])]

            return {
                "success": True,
                "models": models,
                "error": None,
            }
    except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError) as e:
        return {
            "success": False,
            "models": [],
            "error": str(e),
        }


def check_connection(config: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
    """
    Test connection to the configured LLM service.

    Performs a reachability check and a tiny completion request.
    Errors are redacted to avoid leaking secrets.

    Args:
        config: Configuration dictionary.
        timeout: Request timeout in seconds.

    Returns:
        Dict with keys:
        - success: bool
        - reachable: bool (service endpoint reachable)
        - completion_ok: bool (completion request succeeded)
        - error: error message (redacted if contains secret)
        - service: service ID
        - model: model name
    """
    provider = config.get("provider", {})
    service_id = provider.get("service")
    base_url = provider.get("base_url")
    model = provider.get("model")

    if not service_id:
        return {
            "success": False,
            "reachable": False,
            "completion_ok": False,
            "error": "No service configured",
            "service": None,
            "model": None,
        }

    service = get_service(service_id)
    if not service:
        return {
            "success": False,
            "reachable": False,
            "completion_ok": False,
            "error": f"Unknown service: {service_id}",
            "service": service_id,
            "model": model,
        }

    url = base_url or service.default_base_url

    # First, check reachability
    try:
        if service.probe_url:
            probe_url = service.probe_url
        elif service.models_endpoint:
            probe_url = url.rstrip("/") + service.models_endpoint
        else:
            probe_url = url

        req = urllib.request.Request(probe_url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reachable = resp.status < 500
    except (urllib.error.URLError, socket.timeout, OSError):
        reachable = False

    if not reachable:
        return {
            "success": False,
            "reachable": False,
            "completion_ok": False,
            "error": "Service endpoint not reachable",
            "service": service_id,
            "model": model,
        }

    # Try a tiny completion if model is set
    if not model:
        return {
            "success": True,
            "reachable": True,
            "completion_ok": False,
            "error": "No model configured",
            "service": service_id,
            "model": None,
        }

    try:
        # For OpenAI-compatible APIs
        if service.provider_type in ("openai_compatible", "groq"):
            endpoint = url.rstrip("/") + "/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}

            api_key_env = provider.get("api_key_env")
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                response = json.loads(body.decode("utf-8", errors="replace"))
                completion_ok = "choices" in response and len(response["choices"]) > 0
        else:
            # For other providers, skip completion test
            completion_ok = None

        return {
            "success": True,
            "reachable": True,
            "completion_ok": completion_ok,
            "error": None,
            "service": service_id,
            "model": model,
        }
    except Exception as e:
        # Redact error message to avoid leaking secrets
        error_msg = str(e)
        error_msg = error_msg.replace(os.environ.get(provider.get("api_key_env", ""), ""), "*****")
        return {
            "success": False,
            "reachable": True,
            "completion_ok": False,
            "error": error_msg,
            "service": service_id,
            "model": model,
        }


def doctor(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run a diagnostic check on the Cyrrus installation and configuration.

    Checks:
    - Service detection (local services)
    - Configuration validity
    - Database accessibility
    - API key availability (if configured)

    Args:
        config: Configuration dictionary. If None, loads from default location.

    Returns:
        Dict with keys:
        - overall_status: "ok", "warning", or "error"
        - checks: list of check results with keys:
          - name: str
          - status: "ok", "warning", "error"
          - message: str
    """
    if config is None:
        try:
            config = load_config()
        except Exception as e:
            return {
                "overall_status": "error",
                "checks": [
                    {
                        "name": "config_load",
                        "status": "error",
                        "message": f"Failed to load config: {e}",
                    }
                ],
            }

    checks = []

    # Check service detection
    detected = detect_services(timeout=1.0)
    local_services = [sid for sid, reachable in detected.items() if reachable]
    if local_services:
        checks.append({
            "name": "local_services",
            "status": "ok",
            "message": f"Detected: {', '.join(local_services)}",
        })
    else:
        checks.append({
            "name": "local_services",
            "status": "warning",
            "message": "No local services detected",
        })

    # Check provider configuration
    provider = config.get("provider", {})
    service_id = provider.get("service")
    if service_id:
        checks.append({
            "name": "provider_configured",
            "status": "ok",
            "message": f"Service: {service_id}",
        })

        # Check API key if needed
        service = get_service(service_id)
        if service and service.api_key_env_var:
            api_key = os.environ.get(service.api_key_env_var)
            if api_key:
                checks.append({
                    "name": f"api_key_{service.api_key_env_var}",
                    "status": "ok",
                    "message": f"API key set (env var: {service.api_key_env_var})",
                })
            else:
                checks.append({
                    "name": f"api_key_{service.api_key_env_var}",
                    "status": "warning",
                    "message": f"API key not set (env var: {service.api_key_env_var})",
                })
    else:
        checks.append({
            "name": "provider_configured",
            "status": "warning",
            "message": "No service configured",
        })

    # Check database
    db_path = config.get("memory", {}).get("db_path") or default_db_path()
    try:
        db_file = Path(db_path)
        if db_file.exists():
            checks.append({
                "name": "database",
                "status": "ok",
                "message": f"Database at {db_path}",
            })
        else:
            checks.append({
                "name": "database",
                "status": "warning",
                "message": f"Database file not found (will be created): {db_path}",
            })
    except Exception as e:
        checks.append({
            "name": "database",
            "status": "error",
            "message": f"Database check failed: {e}",
        })

    # Check slides file
    slides_path = config.get("context", {}).get("slides_path", "slides.json")
    try:
        slides_file = Path(slides_path)
        if slides_file.exists():
            with open(slides_file) as f:
                slides = json.load(f)
            if "core_lamp" in slides:
                checks.append({
                    "name": "slides_config",
                    "status": "ok",
                    "message": f"Valid slides config at {slides_path}",
                })
            else:
                checks.append({
                    "name": "slides_config",
                    "status": "error",
                    "message": f"Slides config missing core_lamp: {slides_path}",
                })
        else:
            checks.append({
                "name": "slides_config",
                "status": "warning",
                "message": f"Slides config not found: {slides_path}",
            })
    except Exception as e:
        checks.append({
            "name": "slides_config",
            "status": "error",
            "message": f"Slides config check failed: {e}",
        })

    # Determine overall status
    has_error = any(c["status"] == "error" for c in checks)
    has_warning = any(c["status"] == "warning" for c in checks)
    overall = "error" if has_error else ("warning" if has_warning else "ok")

    return {
        "overall_status": overall,
        "checks": checks,
    }


def route_dry_run(text: str, slides_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform a dry run of context routing without calling the LLM.

    Shows which slides would be selected for the given text.

    Args:
        text: Input text to route.
        slides_path: Path to slides.json. If None, uses default "slides.json".

    Returns:
        Dict with keys:
        - success: bool
        - text: input text
        - selected_slides: list of slide IDs that would be included
        - error: error message (if failed)
    """
    if slides_path is None:
        slides_path = "slides.json"

    try:
        slides_file = Path(slides_path)
        if not slides_file.exists():
            return {
                "success": False,
                "text": text,
                "selected_slides": [],
                "error": f"Slides file not found: {slides_path}",
            }

        with open(slides_file) as f:
            slides = json.load(f)

        # Simple keyword-based matching (full routing logic is in projector)
        text_lower = text.lower()
        selected = ["core_lamp"]  # Always include core_lamp

        for slide_id, slide_data in slides.items():
            if slide_id == "core_lamp" or slide_id.startswith("_"):
                continue
            triggers = slide_data.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in text_lower:
                    selected.append(slide_id)
                    break

        return {
            "success": True,
            "text": text,
            "selected_slides": selected,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "text": text,
            "selected_slides": [],
            "error": str(e),
        }


def memory_list(db_path: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """
    List facts from the memory database.

    Args:
        db_path: Path to database file. If None, uses default.
        limit: Maximum number of facts to return.

    Returns:
        Dict with keys:
        - success: bool
        - facts: list of fact dicts (id, content, session_id, created_at)
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "facts": [],
        "error": "Memory integration not yet implemented",
    }


def memory_search(query: str, db_path: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Search for facts in the memory database.

    Args:
        query: Search query.
        db_path: Path to database file. If None, uses default.
        limit: Maximum number of results to return.

    Returns:
        Dict with keys:
        - success: bool
        - results: list of matching fact dicts with scores
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "results": [],
        "error": "Memory integration not yet implemented",
    }


def memory_forget(fact_id: int, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete a specific fact from memory.

    Args:
        fact_id: ID of the fact to delete.
        db_path: Path to database file. If None, uses default.

    Returns:
        Dict with keys:
        - success: bool
        - deleted: bool
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "deleted": False,
        "error": "Memory integration not yet implemented",
    }


def memory_forget_all(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Delete all facts from memory.

    Args:
        db_path: Path to database file. If None, uses default.

    Returns:
        Dict with keys:
        - success: bool
        - count: number of facts deleted
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "count": 0,
        "error": "Memory integration not yet implemented",
    }


def memory_export(db_path: Optional[str] = None, output_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Export memory database to JSON.

    Args:
        db_path: Path to database file. If None, uses default.
        output_path: Path to output JSON file. If None, uses "memory_export.json".

    Returns:
        Dict with keys:
        - success: bool
        - output_path: path to exported file
        - count: number of facts exported
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "output_path": None,
        "count": 0,
        "error": "Memory integration not yet implemented",
    }


def memory_import(input_path: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Import memory database from JSON.

    Args:
        input_path: Path to input JSON file.
        db_path: Path to database file. If None, uses default.

    Returns:
        Dict with keys:
        - success: bool
        - count: number of facts imported
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "count": 0,
        "error": "Memory integration not yet implemented",
    }


def sessions(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    List all conversation sessions.

    Args:
        db_path: Path to database file. If None, uses default.

    Returns:
        Dict with keys:
        - success: bool
        - sessions: list of session dicts (id, created_at, message_count)
        - error: error message (if failed)
    """
    # Placeholder - would integrate with MemoryVault backend
    return {
        "success": False,
        "sessions": [],
        "error": "Memory integration not yet implemented",
    }


def build_projector(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a Projector instance from configuration.

    Args:
        config: Configuration dictionary.

    Returns:
        Dict with keys:
        - success: bool
        - projector_config: dict with projector parameters
        - error: error message (if failed)
    """
    # Placeholder - would build actual Projector instance
    return {
        "success": True,
        "projector_config": {
            "service": config.get("provider", {}).get("service"),
            "model": config.get("provider", {}).get("model"),
            "slides_path": config.get("context", {}).get("slides_path"),
        },
        "error": None,
    }
