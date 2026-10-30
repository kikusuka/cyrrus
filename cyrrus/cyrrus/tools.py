from __future__ import annotations
import asyncio
import concurrent.futures
import json
import os
import socket
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from .services import get_service, detect_services
from .config import load_config, redact_secrets
from .sqlite_backend import default_db_path, get_backend
from .memory import MemoryVault
from .backend import (
    validate_session_id,
    validate_keyword,
    MAX_KEYWORD_LENGTH,
    MAX_FACT_VALUE_LENGTH,
)
from .bm25 import bm25_rank_facts


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
    elif service.provider_type in ("openai_compatible", "openai", "groq"):
        # Hosted OpenAI-compatible APIs expose GET /models
        endpoint = url.rstrip("/") + "/models"
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
        api_key_env = provider.get("api_key_env") or ""
        api_key = os.environ.get(api_key_env, "") if api_key_env else ""
        if api_key:
            error_msg = error_msg.replace(api_key, "*****")
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


def _run_async(coro):
    """Run an async coroutine synchronously, handling running event loops safely."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Resolve database path from argument, config, or system default."""
    if db_path:
        return db_path
    try:
        cfg = load_config()
        configured = cfg.get("memory", {}).get("db_path")
        if configured:
            return configured
    except Exception:
        pass
    return default_db_path()


def _get_memory_vault(db_path: Optional[str] = None) -> MemoryVault:
    """Create a MemoryVault with configured retrieval settings."""
    resolved = _resolve_db_path(db_path)
    embedding_model = None
    embed_min_score = 0.68
    try:
        cfg = load_config()
        mem_cfg = cfg.get("memory", {})
        if mem_cfg.get("retrieval") == "hybrid" or mem_cfg.get("embedding_model"):
            embedding_model = mem_cfg.get("embedding_model") or "BAAI/bge-small-en-v1.5"
        if "embedding_min_score" in mem_cfg:
            embed_min_score = float(mem_cfg["embedding_min_score"])
    except Exception:
        pass
    return MemoryVault(
        db_path=resolved,
        embedding_model=embedding_model,
        embedding_min_score=embed_min_score,
    )


def memory_list(
    session: str = "default",
    include_superseded: bool = False,
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    List facts from the memory database for a session via export_facts.

    Args:
        session: Session identifier.
        include_superseded: If True, include superseded facts.
        db_path: Path to database file. If None, uses config or default.
        limit: Maximum number of facts to return.

    Returns:
        Dict with keys: success, facts, session, error.
    """
    try:
        validate_session_id(session)
        vault = _get_memory_vault(db_path)
        facts = _run_async(vault.export_facts(session, include_superseded=include_superseded))
        if limit is not None and limit > 0:
            facts = facts[:limit]
        return {
            "success": True,
            "facts": facts,
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "facts": [],
            "session": session,
            "error": str(e),
        }


def memory_search(
    session: str = "default",
    query: Optional[str] = None,
    limit: int = 10,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search for facts in the memory database.
    Uses BM25 keyword retrieval by default, and hybrid retrieval if embeddings are configured.

    Args:
        session: Session identifier.
        query: Search query.
        limit: Maximum number of results to return.
        db_path: Path to database file. If None, uses config or default.

    Returns:
        Dict with keys: success, results, session, error.
    """
    try:
        if query is None:
            query = session
            session = "default"

        validate_session_id(session)
        vault = _get_memory_vault(db_path)

        async def _search():
            await vault._ensure_initialized()
            rows = await vault._backend.retrieve_current(session, limit=100)
            if not rows or not query.strip():
                return []

            if vault._embedder is not None and vault._np is not None:
                keyword_ranked = bm25_rank_facts(rows, query, limit=limit, score_threshold=0.0)
                results = []
                seen_keys = set()
                for score, kw, val, tok in keyword_ranked:
                    seen_keys.add(kw)
                    results.append({"key": kw, "value": val, "score": float(score)})

                if len(results) < limit:
                    remaining_rows = [r for r in rows if r[0] not in seen_keys]
                    if remaining_rows:
                        fact_texts = [
                            f"{kw.replace('_', ' ')}: {val}" if val else kw.replace("_", " ")
                            for kw, val, _ in remaining_rows
                        ]
                        query_emb = vault._np.array(list(vault._embedder.embed([query]))[0])
                        fact_embs = vault._np.array(list(vault._embedder.embed(fact_texts)))
                        norms = (
                            vault._np.linalg.norm(fact_embs, axis=1)
                            * vault._np.linalg.norm(query_emb)
                        )
                        norms[norms == 0] = 1e-9
                        scores = fact_embs.dot(query_emb) / norms
                        scored = sorted(zip(scores, remaining_rows), key=lambda x: x[0], reverse=True)
                        for score, (kw, val, tok) in scored:
                            if score >= vault._embedding_min_score:
                                results.append({"key": kw, "value": val, "score": float(score)})
                            if len(results) >= limit:
                                break
                return results[:limit]
            else:
                ranked = bm25_rank_facts(rows, query, limit=limit, score_threshold=0.0)
                return [
                    {"key": kw, "value": val, "score": float(score)}
                    for score, kw, val, tok in ranked
                ]

        results = _run_async(_search())
        return {
            "success": True,
            "results": results,
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "results": [],
            "session": session,
            "error": str(e),
        }


def memory_forget(
    session: str = "default",
    key: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a specific fact from memory via forget_fact.

    Args:
        session: Session identifier.
        key: Fact key to delete.
        db_path: Path to database file. If None, uses config or default.

    Returns:
        Dict with keys: success, deleted, key, session, error.
    """
    try:
        if key is None:
            key = str(session)
            session = "default"

        validate_session_id(session)
        validate_keyword(key)
        vault = _get_memory_vault(db_path)
        deleted = _run_async(vault.forget_fact(session, key))
        return {
            "success": True,
            "deleted": deleted,
            "key": key,
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "deleted": False,
            "key": key or "",
            "session": session,
            "error": str(e),
        }


def memory_forget_all(
    session: str = "default",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete all facts from memory for a session via forget_session.

    Args:
        session: Session identifier.
        db_path: Path to database file. If None, uses config or default.

    Returns:
        Dict with keys: success, count, session, error.
    """
    try:
        validate_session_id(session)
        vault = _get_memory_vault(db_path)
        count = _run_async(vault.forget_session(session))
        return {
            "success": True,
            "count": count,
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "count": 0,
            "session": session,
            "error": str(e),
        }


def memory_export(
    session: str = "default",
    path: Optional[str] = None,
    output_path: Optional[str] = None,
    include_superseded: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export memory facts for a session to JSON.

    Args:
        session: Session identifier.
        path: Output JSON file path.
        output_path: Alias for path.
        include_superseded: If True, include superseded facts.
        db_path: Path to database file. If None, uses config or default.

    Returns:
        Dict with keys: success, output_path, count, facts, session, error.
    """
    try:
        validate_session_id(session)
        vault = _get_memory_vault(db_path)
        facts = _run_async(vault.export_facts(session, include_superseded=include_superseded))
        target_path = path or output_path or "memory_export.json"
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(facts, f, indent=2)
        return {
            "success": True,
            "output_path": str(target_path),
            "count": len(facts),
            "facts": facts,
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "output_path": path or output_path,
            "count": 0,
            "session": session,
            "error": str(e),
        }


def memory_import(
    session: str = "default",
    path: Optional[str] = None,
    input_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Import memory facts for a session from JSON.
    Validates every row before storing; rejects the whole file with a clear error
    if any row is invalid, and stores via the normal upsert path.

    Args:
        session: Session identifier.
        path: Input JSON file path.
        input_path: Alias for path.
        db_path: Path to database file. If None, uses config or default.

    Returns:
        Dict with keys: success, count, session, error.
    """
    try:
        resolved_path = path or input_path
        if resolved_path is None and session and (os.path.exists(session) or session.endswith(".json")):
            resolved_path = session
            session = "default"

        validate_session_id(session)
        if not resolved_path or not os.path.exists(resolved_path):
            return {
                "success": False,
                "count": 0,
                "session": session,
                "error": f"Import file not found: '{resolved_path}'",
            }

        with open(resolved_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as json_err:
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Invalid JSON in '{resolved_path}': {json_err}",
                }

        if not isinstance(data, list):
            return {
                "success": False,
                "count": 0,
                "session": session,
                "error": f"Invalid format in '{resolved_path}': expected JSON array of fact objects",
            }

        # Validate every row before storing
        validated_rows = []
        for idx, row in enumerate(data):
            if not isinstance(row, dict):
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: expected object, got {type(row).__name__}",
                }
            key = row.get("key") if "key" in row else row.get("keyword")
            if key is None or not isinstance(key, str) or not key.strip():
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: missing or empty fact key",
                }
            if len(key) > MAX_KEYWORD_LENGTH:
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: key too long ({len(key)} chars, max {MAX_KEYWORD_LENGTH})",
                }
            try:
                validate_keyword(key)
            except ValueError as ve:
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: {ve}",
                }

            value = row.get("value") if "value" in row else row.get("content")
            if value is None or not isinstance(value, str):
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: missing or invalid fact value",
                }
            if len(value) > MAX_FACT_VALUE_LENGTH:
                return {
                    "success": False,
                    "count": 0,
                    "session": session,
                    "error": f"Row {idx} is invalid: value too long ({len(value)} chars, max {MAX_FACT_VALUE_LENGTH})",
                }
            validated_rows.append((key, value))

        # All rows valid -> store via the normal upsert path
        vault = _get_memory_vault(db_path)

        async def _do_import():
            for key, val in validated_rows:
                toks = max(1, len(val.split()))
                await vault.upsert(session, key, val, toks)

        _run_async(_do_import())
        return {
            "success": True,
            "count": len(validated_rows),
            "session": session,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "count": 0,
            "session": session,
            "error": str(e),
        }


def sessions(db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    List all conversation sessions with active fact counts.

    Args:
        db_path: Path to database file. If None, uses default.

    Returns:
        Dict with keys: success, sessions, error.
    """
    try:
        resolved_db_path = _resolve_db_path(db_path)
        vault = _get_memory_vault(resolved_db_path)
        sess_list = _run_async(vault.list_sessions())
        return {
            "success": True,
            "sessions": sess_list,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "sessions": [],
            "error": str(e),
        }


def build_projector(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a Projector instance configuration from settings.

    Args:
        config: Configuration dictionary.

    Returns:
        Dict with keys: success, projector_config, error.
    """
    # Build projector configuration dictionary from provided settings
    return {
        "success": True,
        "projector_config": {
            "service": config.get("provider", {}).get("service"),
            "model": config.get("provider", {}).get("model"),
            "slides_path": config.get("context", {}).get("slides_path"),
        },
        "error": None,
    }

