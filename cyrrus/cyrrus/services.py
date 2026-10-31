"""
Data-driven registry of LLM services and providers.

Each service definition includes metadata for discovery, configuration,
and usage. Services can be local (self-hosted) or hosted (cloud APIs).
"""
import socket
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class Service:
    """Definition of an LLM service or provider."""
    id: str
    display_name: str
    kind: str  # "local" or "hosted"
    provider_type: str  # "ollama", "openai_compatible", "anthropic", etc.
    default_base_url: str
    probe_url: Optional[str]  # URL to check for reachability (for local services)
    models_endpoint: Optional[str]  # Endpoint to list models
    api_key_env_var: Optional[str]  # Suggested environment variable name
    help_text: str


# Registry of all known services
_SERVICES: Dict[str, Service] = {
    "ollama": Service(
        id="ollama",
        display_name="Ollama",
        kind="local",
        provider_type="ollama",
        default_base_url="http://localhost:11434",
        probe_url="http://localhost:11434/api/tags",
        models_endpoint="/api/tags",
        api_key_env_var=None,
        help_text="Local LLM server. Free, no API key needed. Download from ollama.ai.",
    ),
    "lmstudio": Service(
        id="lmstudio",
        display_name="LM Studio",
        kind="local",
        provider_type="openai_compatible",
        default_base_url="http://localhost:1234/v1",
        probe_url="http://localhost:1234/v1/models",
        models_endpoint="/v1/models",
        api_key_env_var=None,
        help_text="Local LLM server with OpenAI-compatible API. Download from lmstudio.ai.",
    ),
    "llamacpp": Service(
        id="llamacpp",
        display_name="llama.cpp",
        kind="local",
        provider_type="openai_compatible",
        default_base_url="http://localhost:8080/v1",
        probe_url="http://localhost:8080/v1/models",
        models_endpoint="/v1/models",
        api_key_env_var=None,
        help_text="Local LLM server with OpenAI-compatible API. Download from github.com/ggerganov/llama.cpp.",
    ),
    "openai": Service(
        id="openai",
        display_name="OpenAI",
        kind="hosted",
        provider_type="openai",
        default_base_url="https://api.openai.com/v1",
        probe_url=None,
        models_endpoint=None,
        api_key_env_var="OPENAI_API_KEY",
        help_text="OpenAI GPT models. Requires API key from platform.openai.com.",
    ),
    "mistral": Service(
        id="mistral",
        display_name="Mistral AI",
        kind="hosted",
        provider_type="openai_compatible",
        default_base_url="https://api.mistral.ai/v1",
        probe_url=None,
        models_endpoint=None,
        api_key_env_var="MISTRAL_API_KEY",
        help_text="Mistral AI models. Requires API key from console.mistral.ai.",
    ),
    "groq": Service(
        id="groq",
        display_name="Groq",
        kind="hosted",
        provider_type="groq",
        default_base_url="https://api.groq.com/openai/v1",
        probe_url=None,
        models_endpoint=None,
        api_key_env_var="GROQ_API_KEY",
        help_text="Fast inference with generous free tier. Requires API key from console.groq.com.",
    ),
    "openrouter": Service(
        id="openrouter",
        display_name="OpenRouter",
        kind="hosted",
        provider_type="openai_compatible",
        default_base_url="https://openrouter.ai/api/v1",
        probe_url=None,
        models_endpoint=None,
        api_key_env_var="OPENROUTER_API_KEY",
        help_text="Access to many LLM models via a single API. Requires API key from openrouter.ai.",
    ),
    "gemini": Service(
        id="gemini",
        display_name="Google Gemini",
        kind="hosted",
        provider_type="openai_compatible",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        probe_url=None,
        models_endpoint="/models",
        api_key_env_var="GEMINI_API_KEY",
        help_text="Gemini via its OpenAI-compatible endpoint. Requires a Gemini API key.",
    ),
    "anthropic": Service(
        id="anthropic",
        display_name="Anthropic",
        kind="hosted",
        provider_type="anthropic",
        default_base_url="https://api.anthropic.com",
        probe_url=None,
        models_endpoint=None,
        api_key_env_var="ANTHROPIC_API_KEY",
        help_text="Anthropic Claude models. Requires API key from console.anthropic.com.",
    ),
    "custom": Service(
        id="custom",
        display_name="Custom URL",
        kind="local",
        provider_type="openai_compatible",
        default_base_url="http://localhost:8000/v1",
        probe_url=None,
        models_endpoint="/v1/models",
        api_key_env_var=None,
        help_text="User-supplied OpenAI-compatible endpoint. Provide --base-url to configure.",
    ),
}


def get_service(service_id: str) -> Optional[Service]:
    """Get a service definition by ID. Returns None if not found."""
    return _SERVICES.get(service_id)


def list_services() -> List[Service]:
    """Return all registered services."""
    return list(_SERVICES.values())


def list_service_ids() -> List[str]:
    """Return all service IDs."""
    return list(_SERVICES.keys())


def service_to_dict(service: Service) -> Dict[str, Any]:
    """Convert a Service to a dictionary for JSON serialization."""
    return asdict(service)


def _probe_url(url: str, timeout: float = 1.0) -> bool:
    """Check if a URL is reachable with a simple HTTP GET."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 500  # Accept 2xx, 3xx, 4xx as reachable
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def detect_services(timeout: float = 1.0) -> Dict[str, bool]:
    """
    Probe local services and return which are reachable.

    Args:
        timeout: Seconds to wait for each probe. Default 1 second.

    Returns:
        Dictionary mapping service IDs to boolean reachability status.
        Only local services with probe_url are checked.
    """
    results = {}
    for service_id, service in _SERVICES.items():
        if service.kind == "local" and service.probe_url:
            results[service_id] = _probe_url(service.probe_url, timeout)
        else:
            results[service_id] = False  # Hosted services not probed
    return results
