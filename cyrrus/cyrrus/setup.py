"""Guided onboarding wizard: ``cyrrus setup``.

Runs interactively the first time ``ui.onboarded`` is false, and can be
replayed with ``cyrrus --tour`` or ``cyrrus setup``. Non-interactive mode
(``--non-interactive``) accepts a flag for every answer and supports
``--dry-run`` (writes nothing). ``--plain`` disables art, animation and
colour.

The wizard is deliberately thin: every decision is stored in a config dict
and delegated to :mod:`cyrrus.config`, :mod:`cyrrus.services` and
:mod:`cyrrus.tools`; nothing here duplicates that logic. Secrets (API keys)
are never written into config files -- only the environment-variable *name*
is stored in ``cyrrus.config.json``; the value itself, when pasted, goes to
a ``.env`` file (which is added to ``.gitignore``).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import services
from .config import (
    DEFAULTS,
    _deep_merge,
    get_project_config_path,
    get_user_config_path,
    load_config,
    load_config_file,
    redact_secrets,
    save_config_file,
    save_project_config,
    save_user_config,
    update_dotenv,
    validate_config,
)
from .services import detect_services, get_service, list_services
from .tools import check_connection, list_models
from .ui.caps import Caps, COLOR_NONE, detect_caps
from .ui.theme import Theme, should_animate
from .ui.widgets import (
    UI,
    confirm,
    footer,
    hidden_input,
    panel,
    select,
    step_header,
    spinner,
    text_input,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WELCOME_LINES = [
    "Cyrrus puts focused context and memory in front of a model.",
    "Configure it once here; your apps keep chatting exactly as before.",
]

GOALS: List[Tuple[str, str, str]] = [
    (
        "gateway",
        "Gateway",
        "Put Cyrrus in front of my model so apps (editors, chat UIs, bots) "
        "get memory automatically.",
    ),
    (
        "library",
        "Library",
        "Use Cyrrus as a Python library in my own code.",
    ),
    (
        "both",
        "Both",
        "Run the gateway and use the library.",
    ),
]

STARTER_SLIDES: List[Tuple[str, str, Optional[str]]] = [
    (
        "assistant",
        "General assistant",
        "general",
    ),
    (
        "support",
        "Support bot",
        "support",
    ),
    (
        "coding",
        "Coding helper",
        "coding",
    ),
    (
        "discord",
        "Discord bot",
        None,
    ),
    (
        "none",
        "None (blank context)",
        None,
    ),
]

TOKEN_PRESETS: List[Tuple[str, str, int]] = [
    ("small", "Small model", 2000),
    ("medium", "Medium model", 8000),
    ("large", "Large model", 32000),
    ("custom", "Custom", 0),
]

# Sample facts used for the renderer side-by-side demo (step 5).
_DEMO_FACTS = [
    {"id": "mem_user_name", "content": "Fact: Ada"},
    {"id": "mem_user_location", "content": "Fact: Lisbon"},
    {"id": "mem_user_workplace", "content": "Fact: Acme Corp"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key_commands(env_name: str) -> str:
    """Platform-specific commands to set an environment variable."""
    if sys.platform == "win32":
        return (
            "Persistent (reboot not needed for new shells):\n"
            "    setx %s \"value\"\n" % env_name
            + "Current session only:\n"
            "    set %s=value" % env_name
        )
    return 'export %s="value"' % env_name


def _detect_hybrid_available() -> bool:
    """True if numpy and fastembed can be imported (hybrid retrieval)."""
    try:
        import numpy  # noqa: F401
        import fastembed  # noqa: F401
        return True
    except Exception:
        return False


def _renderer_demo(width: int) -> str:
    """Render the same sample facts with the default and compact renderers."""
    from . import renderers
    from .projector import Slide

    base_system = "You are a helpful assistant."
    slides = [Slide(id=f["id"], type="memory", content=f["content"], tokens=8, priority=5)
              for f in _DEMO_FACTS]

    # Default renderer: same logic as Projector._render_system.
    default_lines = [base_system]
    memory_slides = [s for s in slides if s.type == "memory"]
    if memory_slides:
        default_lines.append("")
        for slide in memory_slides:
            raw = slide.content.removeprefix("Fact: ").strip() if slide.content else ""
            default_lines.append("About the user: %s: %s" % (renderers.display_key(slide.id), raw))
    default_render = "\n".join(default_lines)

    compact_render = renderers.compact({
        "slides": [s for s in slides if s.type != "memory"],
        "ghosts": [],
        "facts": slides,
        "base_system": base_system,
    })

    pad = "    "
    lines = ["Default renderer:".ljust(width) + "Compact renderer:"]
    default_lines_split = default_render.splitlines()
    compact_lines_split = compact_render.splitlines()
    n = max(len(default_lines_split), len(compact_lines_split))
    for i in range(n):
        d = default_lines_split[i] if i < len(default_lines_split) else ""
        c = compact_lines_split[i] if i < len(compact_lines_split) else ""
        lines.append("%s%s%s" % (d, pad, c))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core wizard
# ---------------------------------------------------------------------------

def _new_state() -> Dict[str, Any]:
    return {
        "goal": None,
        "provider": {},
        "memory": {},
        "context": {},
        "gateway": {},
        "scope": "project",
        "api_key_env": None,
        "api_key_value": None,
        "start_gateway": False,
        "test_message": False,
    }


def _final_config(state: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the full config dict from wizard state."""
    provider = state["provider"]
    memory = state["memory"]
    context = state["context"]
    gateway = state["gateway"]

    config: Dict[str, Any] = {
        "provider": {
            "service": provider.get("service"),
            "base_url": provider.get("base_url"),
            "model": provider.get("model"),
            "api_key_env": state.get("api_key_env"),
        },
        "memory": {
            "db_path": memory.get("db_path"),
            "retrieval": memory.get("retrieval", "keyword"),
            "max_facts_per_session": memory.get("max_facts_per_session", 50),
            "embedding_min_score": 0.7,
        },
        "context": {
            "renderer": context.get("renderer", "default"),
            "max_context_tokens": context.get("max_context_tokens", 4000),
            "slides_path": context.get("slides_path", "slides.json"),
        },
        "ui": {
            "animation": "off" if state.get("_plain") else "auto",
            "onboarded": True,
        },
    }
    if state.get("goal") in ("gateway", "both"):
        config["gateway"] = {
            "host": gateway.get("host", "127.0.0.1"),
            "port": gateway.get("port", 8787),
            "mode": gateway.get("mode", "inject"),
            "session": gateway.get("session", "default"),
            "fail_open": True,
            "force_model": None,
            "api_key_env": provider.get("api_key_env"),
            "upstream_timeout": 60.0,
        }
    return config


def _slides_for_starter(starter: str) -> Dict[str, Any]:
    """Build a slides.json dict for the chosen starter pack."""
    from .templates import get_template_config

    lamp = {"content": "You are a helpful assistant.", "tokens": 10, "priority": 5}
    slides: Dict[str, Any] = {"core_lamp": lamp}
    if starter == "none":
        return slides
    template = None
    if starter == "assistant":
        template = "general"
    elif starter == "support":
        template = "support"
    elif starter == "coding":
        template = "coding"
    elif starter == "discord":
        template = "support"
    if template is not None:
        try:
            template_cfg = get_template_config(template)
            for key, value in template_cfg.items():
                if key == "core_lamp":
                    slides["core_lamp"] = {
                        "content": value.get("content", lamp["content"]),
                        "tokens": 10,
                        "priority": 5,
                    }
                else:
                    slide = dict(value)
                    slide.setdefault("tokens", 8)
                    slide.setdefault("priority", 5)
                    slides[key] = slide
        except Exception:
            pass
    return slides


def _write_if(path: Path, text: str, dry_run: bool, force: bool, ui: UI) -> bool:
    """Write ``text`` to ``path`` unless dry_run; handle existing-file confirmation."""
    if dry_run:
        ui.write("[dry-run] would write %s" % path)
        return True
    if path.exists() and not force:
        if not confirm(ui, "Overwrite existing %s?" % path, default=False):
            ui.write("Skipped %s." % path)
            return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        ui.write("Wrote %s" % path)
        return True
    except OSError as exc:
        ui.write("Error writing %s: %s" % (path, exc))
        return False


def run_setup(
    ui: UI,
    *,
    non_interactive: bool = False,
    dry_run: bool = False,
    plain: bool = False,
    force: bool = False,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the onboarding wizard and return a result dict.

    The result dict contains: ``config`` (final config), ``written`` (paths
    written), ``dry_run``, ``scope``, ``start_gateway`` and ``test_message``.
    """
    overrides = overrides or {}
    state = _new_state()
    state["_plain"] = plain
    state["_dry_run"] = dry_run
    state["_force"] = force

    caps = ui.caps or detect_caps()
    theme = Theme(caps)
    ansi = caps.ansi and caps.color_depth != COLOR_NONE and not plain

    def write(text: str = "") -> None:
        ui.write(text)
    # ----- Step 1: Welcome -----
    step_header(ui, 1, 7, "Welcome")
    panel(ui, "cyrrus", WELCOME_LINES)
    footer(ui)
    if not non_interactive:
        write("Press Enter to continue...")
        ui.input_fn("")

    # ----- Step 2: Goal -----
    step_header(ui, 2, 7, "What will you use Cyrrus for?")
    options = [(label, key) for key, label, desc in GOALS]
    if non_interactive:
        goal = overrides.get("goal")
        if goal not in ("gateway", "library", "both"):
            raise ValueError("--goal must be gateway, library or both")
        write("Goal: %s" % dict((k, l) for k, l, _ in GOALS)[goal])
    else:
        write("Choose how you'll use Cyrrus:")
        for key, label, desc in GOALS:
            write("  * %s: %s" % (label, desc))
        goal = select(ui, "Choice:", options, default=0)
        if goal is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
    state["goal"] = goal

    # ----- Step 3: Connect your model -----
    step_header(ui, 3, 7, "Connect your model")
    detected = detect_services(timeout=1.0)
    write("Available services:")
    service_options: List[Tuple[str, str]] = []
    for svc in list_services():
        tick = theme.status("ok", "ok") if detected.get(svc.id) else " "
        label = "%s [%s] %s" % (svc.display_name, tick, svc.kind)
        service_options.append((label, svc.id))
        write("  - %s" % label)
    write("")
    if non_interactive:
        service_id = overrides.get("service")
        if not service_id:
            raise ValueError("--service is required in non-interactive mode")
        if get_service(service_id) is None:
            raise ValueError("Unknown service: %s" % service_id)
    else:
        service_id = select(ui, "Select a service:", service_options, default=0)
        if service_id is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
    svc = get_service(service_id)
    base_url = overrides.get("base_url") if non_interactive else None
    if non_interactive and overrides.get("base_url"):
        base_url = overrides["base_url"]
    else:
        base_url = text_input(ui, "Base URL", default=svc.default_base_url or "")
    model = overrides.get("model") if non_interactive else None
    if not model:
        # List models from the server.
        models_result = list_models(service_id, base_url=base_url, timeout=5.0)
        if models_result.get("success") and models_result.get("models"):
            write("Models on %s:" % base_url)
            model_options = [(m, m) for m in models_result["models"]]
            if non_interactive:
                model = overrides.get("model", model_options[0][1] if model_options else None)
            else:
                write("Pick a model (or press Enter to type manually):")
                chosen = select(ui, "Model:", model_options, default=0)
                if chosen is None:
                    return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                            "start_gateway": False, "test_message": False, "cancelled": True}
                model = chosen
        if not model:
            model = text_input(ui, "Model name", default="")
    state["provider"] = {
        "service": service_id,
        "base_url": base_url,
        "model": model,
    }

    # API key.
    api_key_env = None
    api_key_value = None
    if svc.api_key_env_var:
        api_key_env = overrides.get("api_key_env")
        if not api_key_env:
            api_key_env = text_input(ui, "API key environment variable name", default=svc.api_key_env_var or "")
        write("")
        write("Set the key yourself with:")
        write(_key_commands(api_key_env or ""))
        write("")
        api_key_value = overrides.get("api_key") or None
        if not api_key_value and not non_interactive:
            paste = confirm(ui, "Paste the API key now and save it to .env?", default=False)
            if paste:
                api_key_value = hidden_input(ui, "API key (input hidden)")
                api_key_value = api_key_value or None
    state["api_key_env"] = api_key_env
    state["api_key_value"] = api_key_value

    # Test connection.
    test_config = {
        "provider": dict(state["provider"], api_key_env=api_key_env),
    }
    if non_interactive and overrides.get("skip_test") is not True:
        pass
    write("")
    if non_interactive and overrides.get("skip_test"):
        write("(connection test skipped)")
    else:
        def _test():
            return check_connection(test_config, timeout=8.0)
        try:
            result = spinner(ui, "Testing connection", _test)
        except Exception as exc:  # noqa: BLE001
            write(theme.status("failed", "error") + " %s" % exc)
            result = {"reachable": False, "completion_ok": False, "error": str(exc)}
        if result.get("reachable"):
            write(theme.status("reachable", "ok") + " service reachable.")
            if result.get("completion_ok") is True:
                write(theme.status("completion ok", "ok") + " model responded.")
            elif result.get("completion_ok") is False:
                write(theme.status("no completion", "warn") + " reachable but no completion: %s" % (result.get("error") or ""))
            else:
                write("Reachable (completion not tested).")
        else:
            err = (result.get("error") or "").lower()
            write(theme.status("failed", "error") + " connection failed.")
            if "refused" in err or "connect" in err:
                write("Fix: is the service running? (e.g. start Ollama)")
            elif "401" in err or "unauthorized" in err:
                write("Fix: check the API key.")
            elif "model" in err and ("not found" in err or "404" in err):
                write("Fix: pick a model from the list above.")
            else:
                write("Fix: %s" % (result.get("error") or "check the address and key."))
    state["provider"]["api_key_env"] = api_key_env

    # ----- Step 4: Memory -----
    step_header(ui, 4, 7, "Memory")
    hybrid_available = _detect_hybrid_available()
    write("Where should facts be stored?")
    mem_options = [
        ("Per-user folder (%s)" % os.path.expanduser("~"), "user"),
        ("This project folder (cyrrus.db)", "project"),
    ]
    if non_interactive:
        mem_db = overrides.get("memory_db")
        if mem_db == "project":
            db_path = "cyrrus.db"
        else:
            db_path = None  # default
    else:
        write("  * per-user folder: facts follow you across projects")
        write("  * project folder: facts stay in this project")
        mem_db = select(ui, "Storage:", mem_options, default=0)
        if mem_db is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
        db_path = "cyrrus.db" if mem_db == "project" else None
    state["memory"]["db_path"] = db_path

    retrieval = "keyword"
    if non_interactive:
        retrieval = overrides.get("retrieval", "keyword")
        if retrieval not in ("keyword", "hybrid"):
            raise ValueError("--retrieval must be keyword or hybrid")
    else:
        retrieval_options = [("Keyword (default, fast)", "keyword")]
        if hybrid_available:
            retrieval_options.append(("Hybrid (keyword + embeddings)", "hybrid"))
        else:
            write("Hybrid retrieval needs numpy + fastembed:")
            write("    pip install cyrrus[embeddings]")
        write("")
        retrieval = select(ui, "Retrieval:", retrieval_options, default=0)
        if retrieval is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
    state["memory"]["retrieval"] = retrieval

    max_facts = overrides.get("max_facts") if non_interactive else None
    if not max_facts and not non_interactive:
        ans = text_input(ui, "Max facts per session", default="50")
        try:
            max_facts = int(ans) if ans else 50
        except ValueError:
            max_facts = 50
    elif not max_facts:
        max_facts = 50
    state["memory"]["max_facts_per_session"] = max_facts
    write("")
    write("Privacy: facts live in the database above (no cloud). Use "
          "`cyrrus memory forget` or `cyrrus memory export` to manage them.")

    # ----- Step 5: Context style -----
    step_header(ui, 5, 7, "Context style")
    write(_renderer_demo(caps.width or 80))
    write("")
    if non_interactive:
        renderer = overrides.get("renderer", "default")
        if renderer not in ("default", "compact"):
            raise ValueError("--renderer must be default or compact")
        max_tokens = overrides.get("max_context_tokens", 4000)
    else:
        renderer = select(ui, "Renderer:", [
            ("Default (full system message)", "default"),
            ("Compact (known facts only)", "compact"),
        ], default=0)
        if renderer is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
        write("")
        write("Token budget presets:")
        for key, label, val in TOKEN_PRESETS:
            write("  * %s: %s (%d tokens)" % (label, key, val))
        choice = text_input(ui, "Preset [small/medium/large/custom]", default="medium")
        preset = dict((k, v) for k, _, v in TOKEN_PRESETS)
        max_tokens = preset.get(choice, 4000)
        if choice == "custom":
            ans = text_input(ui, "Custom token budget", default="4000")
            try:
                max_tokens = int(ans) if ans else 4000
            except ValueError:
                max_tokens = 4000
    state["context"]["renderer"] = renderer
    state["context"]["max_context_tokens"] = max_tokens

    # Starter slide pack.
    if non_interactive:
        starter = overrides.get("starter_slide", "assistant")
        if starter not in ("assistant", "support", "coding", "discord", "none"):
            raise ValueError("unknown starter slide: %s" % starter)
    else:
        write("")
        write("Starter slide pack (written to slides.json):")
        starter = select(ui, "Starter pack:", [(label, key) for key, label, _ in STARTER_SLIDES], default=0)
        if starter is None:
            return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": True}
    state["context"]["slides_path"] = "slides.json"
    state["_starter"] = starter

    # ----- Step 6: Gateway (conditional) -----
    if state["goal"] in ("gateway", "both"):
        step_header(ui, 6, 7, "Gateway")
        if non_interactive:
            port = overrides.get("gateway_port", 8787)
            mode = overrides.get("gateway_mode", "inject")
            if mode not in ("inject", "manage"):
                raise ValueError("--gateway-mode must be inject or manage")
            session = overrides.get("gateway_session", "default")
        else:
            write("Cyrrus serves an OpenAI-compatible gateway that injects context.")
            port_input = text_input(ui, "Port", default="8787")
            try:
                port = int(port_input) if port_input else 8787
            except ValueError:
                port = 8787
            mode = select(ui, "Mode:", [("Inject context (recommended)", "inject"),
                                         ("Compact history (manage)", "manage")], default=0)
            if mode is None:
                return {"config": {}, "written": [], "dry_run": dry_run, "scope": "project",
                        "start_gateway": False, "test_message": False, "cancelled": True}
            session = text_input(ui, "Default session", default="default")
        state["gateway"] = {"host": "127.0.0.1", "port": port, "mode": mode, "session": session}
        write("")
        write("Copy-ready snippets (set the base URL to http://127.0.0.1:%d/v1):" % port)
        write("  Zed: language_models.openai_compatible with api_url http://127.0.0.1:%d/v1" % port)
        write("  Python: openai.OpenAI(base_url='http://127.0.0.1:%d/v1')" % port)
        write("  curl: curl http://127.0.0.1:%d/v1/chat/completions ..." % port)

    # ----- Step 7: Review & save -----
    step_header(ui, 7, 7, "Review")
    config = _final_config(state)
    panel(ui, "Ready to save", [
        "Provider: %s" % (config["provider"].get("service") or "not selected"),
        "Model: %s" % (config["provider"].get("model") or "not set"),
        "Memory: %s / %s" % (config["memory"].get("db_path") or "default", config["memory"].get("retrieval")),
        "Renderer: %s / %d tokens" % (config["context"].get("renderer"), config["context"].get("max_context_tokens")),
        "Gateway: %s" % (config.get("gateway", {}).get("mode", "not enabled")),
        "Starter: %s" % state.get("_starter", "none"),
    ])
    footer(ui)
    write("")
    write("Secrets are redacted. The API key value, if pasted, goes only to .env.")

    if non_interactive:
        save_it = overrides.get("yes", False)
    else:
        save_it = confirm(ui, "Save configuration now?", default=True)
    if not save_it:
        write("Configuration not saved.")
        return {"config": config, "written": [], "dry_run": dry_run, "scope": "project",
                "start_gateway": False, "test_message": False, "cancelled": False}

    # Scope.
    if non_interactive:
        scope = overrides.get("scope", "project")
        if scope not in ("project", "user"):
            raise ValueError("--scope must be project or user")
    else:
        scope = select(ui, "Save to:", [("Project (cyrrus.config.json)", "project"),
                                          ("User (%s)" % get_user_config_path(), "user")], default=0)
        if scope is None:
            return {"config": config, "written": [], "dry_run": dry_run, "scope": "project",
                    "start_gateway": False, "test_message": False, "cancelled": False}
    state["scope"] = scope

    written: List[str] = []

    # Write cyrrus.config.json (secrets redacted).
    save_config = dict(config)
    save_config["ui"]["onboarded"] = True
    red = redact_secrets(save_config)
    target = get_project_config_path() if scope == "project" else get_user_config_path()
    if _write_if(target, json.dumps(red, indent=2) + "\n", dry_run, force, ui):
        written.append(str(target))

    # Write .env with API key value (if pasted).
    if state.get("api_key_value"):
        env_target = Path.cwd() / ".env"
        env_line = "%s=%s\n" % (state["api_key_env"], state["api_key_value"])
        if _write_if(env_target, env_line, dry_run, force, ui):
            written.append(str(env_target))
        # update_dotenv also ensures .gitignore lists .env (only when not dry_run/force safe).
        if not dry_run:
            try:
                update_dotenv(state["api_key_env"], state["api_key_value"])
            except Exception:
                pass

    # Write slides.json.
    slides = _slides_for_starter(state.get("_starter", "assistant"))
    slides_target = Path.cwd() / state["context"]["slides_path"]
    if _write_if(slides_target, json.dumps(slides, indent=2) + "\n", dry_run, force, ui):
        written.append(str(slides_target))

    write("")
    write("Setup complete. Cyrrus is configured.")
    start_gw = False
    test_msg = False
    if state["goal"] in ("gateway", "both"):
        if non_interactive:
            start_gw = bool(overrides.get("start_gateway"))
            test_msg = bool(overrides.get("test_message"))
        else:
            start_gw = confirm(ui, "Start the gateway now?", default=False)
            if start_gw:
                test_msg = confirm(ui, "Send a test message through the gateway?", default=False)
    return {
        "config": config,
        "written": written,
        "dry_run": dry_run,
        "scope": scope,
        "start_gateway": start_gw,
        "test_message": test_msg,
        "cancelled": False,
    }


# ---------------------------------------------------------------------------
# Snippets
# ---------------------------------------------------------------------------

def snippet(kind: str, port: int = 8787) -> str:
    """Return a copy-ready snippet for ``zed``, ``python`` or ``curl``."""
    base = "http://127.0.0.1:%d/v1" % port
    if kind == "zed":
        return json.dumps({
            "language_models": {
                "openai_compatible": {
                    "api_url": base,
                    "available_models": [{
                        "name": "cyrrus",
                        "display_name": "Cyrrus",
                        "max_tokens": 4096,
                        "capabilities": {
                            "tools": True,
                            "images": True,
                            "parallel_tool_calls": True,
                            "prompt_cache_key": "cyrrus",
                        },
                    }],
                }
            }
        }, indent=2)
    if kind == "python":
        return "\n".join([
            "from openai import OpenAI",
            "client = OpenAI(base_url='%s')" % base,
            "client.chat.completions.create(model='cyrrus', "
            "messages=[{'role': 'user', 'content': 'hello'}])",
        ])
    if kind == "curl":
        return "\n".join([
            "curl %s/v1/chat/completions \\" % base,
            "  -H \"Content-Type: application/json\" \\",
            "  -d '{\"model\":\"cyrrus\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'",
        ])
    raise ValueError("unknown snippet kind: %s" % kind)
