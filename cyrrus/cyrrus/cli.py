from __future__ import annotations
"""Interactive command-line tools for cyrrus."""

import argparse
import json
import sys
import os
from typing import Any, Dict, Optional, Sequence
from pathlib import Path

from .templates import (
    PERSONALITIES,
    TEMPLATES,
    get_template_config,
    list_personalities,
    list_templates,
    match_template,
)
from .services import list_services, detect_services, get_service
from .config import (
    load_config,
    save_project_config,
    save_user_config,
    redact_secrets,
    get_project_config_path,
    get_user_config_path,
    update_dotenv,
)
from .tools import (
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
)
from .ui.caps import detect_caps
from .ui.theme import should_animate


def is_interactive() -> bool:
    """Return whether both standard streams support interactive input."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt(message: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    response = input(f"{message}{suffix}: ").strip()
    return response if response else (default or "")


def prompt_choice(message: str, choices: Sequence[str], default: int = 1) -> int:
    print(f"\n{message}")
    for number, choice in enumerate(choices, 1):
        marker = " (default)" if number == default else ""
        print(f"  {number}. {choice}{marker}")

    while True:
        response = input(f"Select option [1-{len(choices)}] [{default}]: ").strip()
        if not response:
            return default - 1
        try:
            selected = int(response)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(choices):
            return selected - 1
        print(f"Please enter a number between 1 and {len(choices)}.")


def select_template_interactive() -> str:
    templates = list_templates()
    choices = [f"{name} — {description}" for _, name, description in templates]
    choices.append("Describe it yourself")
    selected = prompt_choice("What should your bot do?", choices)
    if selected < len(templates):
        return templates[selected][0]

    description = prompt("Describe what your bot should do")
    suggestion = match_template(description)
    if suggestion:
        info = TEMPLATES[suggestion]
        print(f"\nClosest match: {info['name']} — {info['description']}")
        if prompt("Use this template? (Y/n)", "y").lower() in {"", "y", "yes"}:
            return suggestion

    print("\nChoose a different template:")
    return templates[prompt_choice("Available templates:", choices[:-1])][0]


def select_personality_interactive() -> Optional[str]:
    choices = list_personalities() + ["Describe it yourself", "Skip"]
    selected = prompt_choice("What's the personality/tone?", choices)
    if selected < len(PERSONALITIES):
        return choices[selected]
    if choices[selected] == "Skip":
        return None
    return prompt("Describe the personality/tone") or None


def show_preview(config: dict) -> None:
    print("\nGenerated slides.json preview:")
    print(json.dumps(config, indent=2))


def write_config(config: dict, output: str) -> None:
    try:
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        print(f"Error writing {output}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Configuration written to {output}")


def interactive_mode(template: Optional[str], tone: Optional[str], output: str) -> None:
    print("Cyrrus configuration wizard")
    selected_template = template or select_template_interactive()
    selected_tone = tone if tone is not None else select_personality_interactive()
    config = get_template_config(selected_template, selected_tone)
    show_preview(config)
    if prompt("Look good? (Y/n)", "y").lower() not in {"", "y", "yes"}:
        print("Configuration cancelled.")
        return
    write_config(config, output)


def non_interactive_mode(template: Optional[str], tone: Optional[str], output: str) -> None:
    missing = []
    if not template:
        missing.append("--template")
    if not tone:
        missing.append("--tone")
    if missing:
        flags = " and ".join(missing)
        print(
            f"Error: non-interactive mode requires {flags}. "
            "Use `cyrrus init --template coding --tone professional --yes`.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    write_config(get_template_config(template, tone), output)


def cmd_init(args) -> None:
    """Handle the init command (existing functionality)."""
    non_interactive = args.no_input or args.yes or not is_interactive()
    if non_interactive:
        non_interactive_mode(args.template, args.tone, args.output)
    else:
        interactive_mode(args.template, args.tone, args.output)


def _doctor_symbol(status: str) -> str:
    """Return a status marker that the current stdout encoding can print."""
    symbol = {"ok": "✓", "warning": "!", "error": "✗"}.get(status, "?")
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        symbol.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return {"ok": "OK", "warning": "!", "error": "X"}.get(status, "?")
    return symbol


def cmd_doctor(args) -> None:
    """Run diagnostic checks."""
    config = load_config(project_dir=Path(args.config) if args.config else None)
    result = doctor(config)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Overall status: {result['overall_status'].upper()}")
        print()
        for check in result["checks"]:
            status_symbol = _doctor_symbol(check["status"])
            print(f"{status_symbol} {check['name']}: {check['message']}")


def cmd_connect(args) -> None:
    """Configure and test connection to a service."""
    service = get_service(args.service)
    if not service:
        print(f"Error: Unknown service '{args.service}'", file=sys.stderr)
        print(f"Available services: {', '.join([s.id for s in list_services()])}", file=sys.stderr)
        raise SystemExit(1)

    config = load_config(project_dir=Path(args.config) if args.config else None)

    # Update config with provided values
    config["provider"]["service"] = args.service
    if args.base_url:
        config["provider"]["base_url"] = args.base_url
    if args.model:
        config["provider"]["model"] = args.model
    if args.api_key_env:
        config["provider"]["api_key_env"] = args.api_key_env

    # Save if requested
    if args.save:
        if args.save == "project":
            save_project_config(config)
            print(f"Configuration saved to {get_project_config_path()}")
        elif args.save == "user":
            save_user_config(config)
            print(f"Configuration saved to {get_user_config_path()}")

        # Update .env if API key env var is set
        if args.api_key_env and args.api_key:
            update_dotenv(args.api_key_env, args.api_key)
            print(f"API key added to .env")

    # Test connection if requested
    if args.test:
        result = check_connection(config)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Service: {result['service']}")
            print(f"Model: {result['model'] or 'Not set'}")
            print(f"Reachable: {result['reachable']}")
            if result['completion_ok'] is not None:
                print(f"Completion OK: {result['completion_ok']}")
            if result['error']:
                print(f"Error: {result['error']}")
    else:
        print(f"Service configured: {args.service}")
        if args.model:
            print(f"Model: {args.model}")


def cmd_services(args) -> None:
    """List available services with detection status."""
    services = list_services()
    detected = detect_services(timeout=1.0)

    if args.json:
        output = []
        for service in services:
            output.append({
                "id": service.id,
                "display_name": service.display_name,
                "kind": service.kind,
                "detected": detected.get(service.id, False),
            })
        print(json.dumps(output, indent=2))
    else:
        print("Available services:")
        for service in services:
            status = "✓" if detected.get(service.id) else " "
            print(f"  [{status}] {service.display_name} ({service.id}) - {service.kind}")


def cmd_models(args) -> None:
    """List models for a service."""
    config = load_config(project_dir=Path(args.config) if args.config else None)
    provider = config.get("provider", {})
    service_id = args.service or provider.get("service")
    base_url = args.base_url or provider.get("base_url")

    if not service_id:
        print("Error: No service configured. Use --service or configure with 'cyrrus connect'", file=sys.stderr)
        raise SystemExit(1)

    result = list_models(service_id, base_url=base_url, timeout=args.timeout)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"Models for {service_id}:")
            for model in result["models"]:
                print(f"  - {model}")
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
            raise SystemExit(1)


def cmd_route(args) -> None:
    """Perform a dry run of context routing."""
    config = load_config(project_dir=Path(args.config) if args.config else None)
    slides_path = args.slides or config.get("context", {}).get("slides_path", "slides.json")

    result = route_dry_run(args.text, slides_path=slides_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"Input: {result['text']}")
            print(f"Selected slides: {', '.join(result['selected_slides'])}")
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
            raise SystemExit(1)


def cmd_memory(args) -> None:
    """Memory operations."""
    config = load_config(project_dir=Path(args.config) if getattr(args, "config", None) else None)
    db_path = getattr(args, "db", None) or config.get("memory", {}).get("db_path")
    session = getattr(args, "session", None) or "default"

    if args.action == "list":
        limit = getattr(args, "limit", None)
        include_superseded = getattr(args, "include_superseded", False)
        result = memory_list(session=session, include_superseded=include_superseded, db_path=db_path, limit=limit)
    elif args.action == "search":
        limit = getattr(args, "limit", 10)
        result = memory_search(session=session, query=args.query, limit=limit, db_path=db_path)
    elif args.action == "forget":
        key = getattr(args, "key", None)
        if key is None and hasattr(args, "fact_id"):
            key = str(args.fact_id)
        if not key:
            print("Error: Fact key required for forget", file=sys.stderr)
            raise SystemExit(1)
        if not getattr(args, "yes", False):
            if is_interactive():
                ans = prompt(f"Delete fact '{key}' for session '{session}'? (y/N)", "n").lower()
                if ans not in ("y", "yes"):
                    print("Operation cancelled.", file=sys.stderr)
                    raise SystemExit(1)
            else:
                print("Error: --yes required for destructive operations", file=sys.stderr)
                raise SystemExit(1)
        result = memory_forget(session=session, key=key, db_path=db_path)
    elif args.action == "forget-all":
        if not getattr(args, "yes", False):
            if is_interactive():
                ans = prompt(f"Delete ALL facts for session '{session}'? (y/N)", "n").lower()
                if ans not in ("y", "yes"):
                    print("Operation cancelled.", file=sys.stderr)
                    raise SystemExit(1)
            else:
                print("Error: --yes required for destructive operations", file=sys.stderr)
                raise SystemExit(1)
        result = memory_forget_all(session=session, db_path=db_path)
    elif args.action == "export":
        out_path = getattr(args, "file", None) or getattr(args, "output", None) or getattr(args, "path", None)
        include_superseded = getattr(args, "include_superseded", False)
        result = memory_export(session=session, path=out_path, include_superseded=include_superseded, db_path=db_path)
    elif args.action == "import":
        in_path = getattr(args, "file", None) or getattr(args, "input", None) or getattr(args, "path", None)
        if not in_path:
            print("Error: Input file path required for import", file=sys.stderr)
            raise SystemExit(1)
        result = memory_import(session=session, path=in_path, db_path=db_path)
    else:
        print(f"Error: Unknown action '{args.action}'", file=sys.stderr)
        raise SystemExit(1)

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        if not result.get("success", False):
            raise SystemExit(1)
    else:
        if result.get("success", False):
            if args.action == "list":
                facts = result.get("facts", [])
                print(f"Facts ({len(facts)}):")
                for fact in facts:
                    k = fact.get("key") or fact.get("id") or ""
                    v = fact.get("value") or fact.get("content") or ""
                    extra = " [superseded]" if fact.get("invalid_at") else ""
                    print(f"  [{k}] {v}{extra}")
            elif args.action == "search":
                results = result.get("results", [])
                print(f"Results ({len(results)}):")
                for r in results:
                    k = r.get("key", "")
                    v = r.get("value", r.get("content", ""))
                    score = r.get("score")
                    score_str = f" (score: {score:.4f})" if isinstance(score, float) else (f" (score: {score})" if score is not None else "")
                    print(f"  - [{k}] {v}{score_str}")
            elif args.action == "forget":
                k = result.get("key", "")
                print(f"Fact '{k}' deleted" if result.get("deleted") else "Delete failed")
            elif args.action == "forget-all":
                print(f"Deleted {result.get('count', 0)} facts")
            elif args.action == "export":
                print(f"Exported {result.get('count', 0)} facts to {result.get('output_path')}")
            elif args.action == "import":
                print(f"Imported {result.get('count', 0)} facts")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            raise SystemExit(1)


def cmd_sessions(args) -> None:
    """List conversation sessions."""
    config = load_config(project_dir=Path(args.config) if getattr(args, "config", None) else None)
    db_path = getattr(args, "db", None) or config.get("memory", {}).get("db_path")

    result = sessions(db_path=db_path)

    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        if not result.get("success", False):
            raise SystemExit(1)
    else:
        if result.get("success", False):
            sess_list = result.get("sessions", [])
            print(f"Sessions ({len(sess_list)}):")
            for sess in sess_list:
                sid = sess.get("session_id") or sess.get("id")
                count = sess.get("active_facts", sess.get("fact_count", 0))
                print(f"  [{sid}] ({count} active facts)")
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            raise SystemExit(1)



def cmd_config(args) -> None:
    """Configuration operations."""
    config = load_config(project_dir=Path(args.config) if args.config else None)

    if args.action == "show":
        result = redact_secrets(config)
    elif args.action == "get":
        keys = args.key.split(".")
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                print(f"Error: Key '{args.key}' not found", file=sys.stderr)
                raise SystemExit(1)
        result = value
    elif args.action == "set":
        keys = args.key.split(".")
        current = config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        current[keys[-1]] = args.value
        save_project_config(config)
        result = {"key": args.key, "value": args.value}
    elif args.action == "path":
        result = {
            "project": str(get_project_config_path()),
            "user": str(get_user_config_path()),
        }
    else:
        print(f"Error: Unknown action '{args.action}'", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if args.action == "show":
            print(json.dumps(result, indent=2))
        elif args.action == "get":
            print(json.dumps(result, indent=2))
        elif args.action == "set":
            print(f"Set {args.key} = {args.value}")
        elif args.action == "path":
            print(f"Project config: {result['project']}")
            print(f"User config: {result['user']}")


def cmd_intro(args) -> None:
    """Play the intro animation (new command)."""
    from .ui import anim

    config = load_config(
        project_dir=Path(args.config) if getattr(args, "config", None) else None
    )
    caps = detect_caps()
    if args.quick:
        mode = "quick"
    elif args.static:
        mode = "static"
    else:
        mode = "full"
    if (
        args.no_anim
        or getattr(args, "plain", False)
        or config.get("ui", {}).get("animation", "auto") == "off"
        or not should_animate(caps, config, "interactive")
    ):
        mode = "static"
    # Never clear the screen: ``cyrrus intro`` must always end on the
    # one-line header, never a blank screen.
    anim.play_intro(
        caps,
        sys.stdout,
        anim.real_sleep,
        anim._real_kbhit,
        mode=mode,
        tier=args.tier,
        clear_after=False,
    )
    print("cyrrus · by Breezy Labs")


def _entry_intro(args, config, mode: str) -> None:
    """Play the intro before entering the wizard or home menu, when allowed."""
    from .ui import anim
    from .ui.caps import detect_caps
    from .ui.theme import should_animate

    if getattr(args, "no_anim", False) or getattr(args, "plain", False):
        return
    caps = detect_caps()
    if not should_animate(caps, config, "interactive"):
        return
    anim.play_intro(
        caps, sys.stdout, anim.real_sleep, anim._real_kbhit,
        mode=mode, clear_after=True,
    )


def cmd_logo(args) -> None:
    """Show the static logo (new command)."""
    from .ui import anim

    caps = detect_caps()
    anim.play_intro(
        caps,
        sys.stdout,
        anim.real_sleep,
        anim._real_kbhit,
        mode="static",
        tier=args.tier,
    )


def cmd_serve(args) -> None:
    """Run the local OpenAI-compatible context gateway."""
    from .gateway import serve
    config = load_config(project_dir=Path(args.config) if args.config else None)
    banner = (
        f"\n  Cyrrus gateway\n"
        f"  Model: {config.get('provider', {}).get('model', '?')}\n"
        f"  Mode:  {config.get('gateway', {}).get('mode', 'inject')}\n"
        f"  URL:   http://127.0.0.1:{config.get('gateway', {}).get('port', 8787)}/v1\n"
        f"  Session: {config.get('gateway', {}).get('session', 'default')}\n"
        f"  Press Ctrl+C to stop\n"
        f"  Paste this URL into your editor/chat UI.\n"
    )
    print(banner, end="")
    serve(config, host=args.host, port=args.port, log_prompts=args.log_prompts)


def cmd_home(args) -> None:
    """Show the compact home menu.

    The status panel above is rendered with the same panel widget as the
    wizard (rounded Unicode when the terminal supports it, ASCII as a
    fallback), so every row is padded to the same width and the right border
    sits in a single column. Below it there is exactly one way to choose: an
    arrow-key select list that falls back to a numbered list only when keys
    are unavailable (non-TTY).
    """
    from .ui.caps import detect_caps
    from .ui.widgets import UI, panel, select
    config = load_config(project_dir=Path(getattr(args, "config", None)) if getattr(args, "config", None) else None)
    gateway = config.get("gateway", {})
    provider = config.get("provider", {})
    memory = config.get("memory", {})
    context = config.get("context", {})

    ui = UI(caps=detect_caps())
    ui.write("cyrrus · by Breezy Labs")
    ui.write("")
    panel(ui, "cyrrus home", [
        "Gateway:  %s" % gateway.get("mode", "inject"),
        "Model:    %s" % provider.get("service", "none"),
        "Memory:   %s" % memory.get("retrieval", "keyword"),
        "Renderer: %s" % context.get("renderer", "default"),
    ])
    ui.write("")
    choice = select(ui, "Choose an action:", [
        ("Start gateway", "serve"), ("Connect a model", "connect"),
        ("Memory", "memory"), ("Context style", "context"),
        ("App snippets", "snippets"), ("Doctor", "doctor"),
        ("Re-run setup", "setup"), ("Quit", "quit"),
    ])
    if choice == "setup":
        cmd_setup(args)
    elif choice == "doctor":
        cmd_doctor(args)
    elif choice == "snippets":
        from .setup import snippet
        ui.write(snippet("zed", port=gateway.get("port", 8787)))
    elif choice and choice != "quit":
        ui.write("Use `cyrrus %s` to continue." % choice)


def cmd_logs(args) -> None:
    """Print the last traces from a running gateway's /cyrrus/last."""
    import urllib.request
    import urllib.error

    base = getattr(args, "base_url", None) or "http://127.0.0.1:8787"
    url = f"{base}/cyrrus/last"

    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"Gateway responded with error (HTTP {exc.code}): {exc.reason}")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach gateway at {url}: {exc}")
        return

    traces = data.get("requests", [])
    if not traces:
        print("No traces available - no requests yet.")
        return

    # Render nicely without JSON module import at top
    for trace in traces:
        path = trace.get("path", "?")
        method = trace.get("method", "?")
        # Truncate prompt text if present
        prompt_text = trace.get("prompt", "")[:30] if trace.get("prompt") else ""
        print(f"  {method} {path}")
        if prompt_text:
            print(f"        prompt: {prompt_text}")


def cmd_setup(args) -> None:
    """Run the guided onboarding wizard."""
    from .setup import run_setup, snippet
    from .ui.caps import detect_caps
    from .ui.widgets import UI

    non_interactive = (
        getattr(args, "no_input", False)
        or getattr(args, "non_interactive", False)
        or getattr(args, "yes", False)
        or not is_interactive()
    )
    dry_run = getattr(args, "dry_run", False)
    plain = getattr(args, "plain", False)
    force = getattr(args, "force", False) or (non_interactive and getattr(args, "yes", False))
    setup_action = getattr(args, "setup_action", None)
    if getattr(args, "unsafe_api_key", None) is not None:
        raise SystemExit("--api-key is unsafe because command lines leak into shell history and process lists; use --api-key-env NAME or --api-key-stdin instead.")

    if setup_action == "show":
        kind = getattr(args, "kind", None)
        port = getattr(args, "port", 8787) or 8787
        print(snippet(kind, port=port))
        return

    overrides: Dict[str, Any] = {}
    if getattr(args, "api_key_stdin", False):
        overrides["api_key"] = sys.stdin.read().strip() or None
    if getattr(args, "api_key_env", None):
        overrides["api_key_env"] = args.api_key_env
    if non_interactive:
        for attr in ("goal", "service", "base_url", "model", "api_key_env",
                     "memory_db", "retrieval", "renderer", "max_context_tokens",
                     "starter_slide", "gateway_mode", "gateway_session", "scope"):
            val = getattr(args, attr, None)
            if val is not None:
                overrides[attr] = val
        for attr in ("max_facts", "gateway_port"):
            val = getattr(args, attr, None)
            if val is not None:
                overrides[attr] = val
        if getattr(args, "start_gateway", False):
            overrides["start_gateway"] = True
        if getattr(args, "test_message", False):
            overrides["test_message"] = True
        if getattr(args, "skip_test", False):
            overrides["skip_test"] = True
        if getattr(args, "yes", False):
            overrides["yes"] = True

    ui = UI(caps=detect_caps())
    result = run_setup(ui,
        non_interactive=non_interactive,
        dry_run=dry_run,
        plain=plain,
        force=force,
        overrides=overrides,
    )
    if result.get("cancelled"):
        print("Onboarding cancelled.")
        return
    if not dry_run and result.get("written"):
        print("")
        print("Saved:")
        for path in result["written"]:
            print("  %s" % path)

    if result.get("start_gateway"):
        # Run the gateway in the foreground with the banner (blocking until
        # the user stops it with Ctrl+C).
        from .gateway import serve
        serve(result["config"])


def build_parser() -> argparse.ArgumentParser:
    # Shared so both `cyrrus --json CMD` and `cyrrus CMD --json` work, along with --db, --session, --yes
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="output JSON")
    json_parent.add_argument("--config", default=argparse.SUPPRESS, help="path to project config file")
    json_parent.add_argument("--db", default=argparse.SUPPRESS, help="path to memory database")
    json_parent.add_argument("--session", default=argparse.SUPPRESS, help="session ID (default: 'default')")
    json_parent.add_argument("--yes", "-y", action="store_true", default=argparse.SUPPRESS, help="skip confirmation / confirm destructive operations")

    parser = argparse.ArgumentParser(description="Cyrrus context routing for LLM calls", parents=[json_parent])
    parser.add_argument("--version", action="version", version="cyrrus 0.3.0b6")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument("--no-anim", action="store_true", help="disable the intro animation")
    parser.add_argument("--tour", action="store_true", help="replay the guided onboarding")
    parser.add_argument("--plain", action="store_true", help="disable art, animation and colour")

    commands = parser.add_subparsers(dest="command", help="Available commands")

    # init command (existing)
    init = commands.add_parser("init", parents=[json_parent], help="create a slides.json configuration")
    init.add_argument("--template", "-t", choices=list(TEMPLATES), help="bot template")
    init.add_argument("--tone", "--personality", dest="tone", help="personality/tone")
    init.add_argument("--output", "-o", default="slides.json", help="output path")
    init.add_argument("--no-input", action="store_true", help="force non-interactive mode")

    # doctor command
    doctor_cmd = commands.add_parser("doctor", parents=[json_parent], help="run diagnostic checks")

    # connect command
    connect = commands.add_parser("connect", parents=[json_parent], help="configure and test service connection")
    connect.add_argument("--service", required=True, help="service ID")
    connect.add_argument("--model", help="model name")
    connect.add_argument("--base-url", help="override base URL")
    connect.add_argument("--api-key-env", help="API key environment variable name")
    connect.add_argument("--api-key", help="API key value (for .env)")
    connect.add_argument("--test", action="store_true", help="test connection")
    connect.add_argument("--save", choices=["project", "user"], help="save configuration")

    # services command
    services_cmd = commands.add_parser("services", parents=[json_parent], help="list available services")

    # models command
    models = commands.add_parser("models", parents=[json_parent], help="list models for a service")
    models.add_argument("--service", help="service ID (uses configured if not set)")
    models.add_argument("--base-url", help="override base URL")
    models.add_argument("--timeout", type=float, default=5.0, help="request timeout")

    # route command
    route = commands.add_parser("route", parents=[json_parent], help="dry run of context routing")
    route.add_argument("text", help="input text to route")
    route.add_argument("--slides", help="path to slides.json")

    # memory command
    memory = commands.add_parser("memory", parents=[json_parent], help="memory operations")
    memory_sub = memory.add_subparsers(dest="action", required=True)
    memory_list_cmd = memory_sub.add_parser("list", parents=[json_parent], help="list facts")
    memory_list_cmd.add_argument("--limit", type=int, default=100, help="max facts to return")
    memory_list_cmd.add_argument("--include-superseded", "--all", action="store_true", default=False, help="include superseded facts")
    memory_search_cmd = memory_sub.add_parser("search", parents=[json_parent], help="search facts")
    memory_search_cmd.add_argument("query", help="search query")
    memory_search_cmd.add_argument("--limit", type=int, default=10, help="max results")
    memory_forget_cmd = memory_sub.add_parser("forget", parents=[json_parent], help="delete a fact")
    memory_forget_cmd.add_argument("key", help="fact key to delete")
    memory_forget_all_cmd = memory_sub.add_parser("forget-all", parents=[json_parent], help="delete all facts")
    memory_export_cmd = memory_sub.add_parser("export", parents=[json_parent], help="export facts to JSON")
    memory_export_cmd.add_argument("path", nargs="?", default=None, help="output file path")
    memory_export_cmd.add_argument("--file", "-f", "--output", "-o", dest="file", help="output file path")
    memory_export_cmd.add_argument("--include-superseded", "--all", action="store_true", default=False, help="include superseded facts")
    memory_import_cmd = memory_sub.add_parser("import", parents=[json_parent], help="import facts from JSON")
    memory_import_cmd.add_argument("path", nargs="?", default=None, help="input file path")
    memory_import_cmd.add_argument("--file", "-f", "--input", "-i", dest="file", help="input file path")

    # sessions command
    sessions_cmd = commands.add_parser("sessions", parents=[json_parent], help="list conversation sessions")

    # config command
    config_cmd = commands.add_parser("config", parents=[json_parent], help="configuration operations")
    config_sub = config_cmd.add_subparsers(dest="action", required=True)
    config_sub.add_parser("show", parents=[json_parent], help="show configuration (secrets redacted)")
    config_get = config_sub.add_parser("get", parents=[json_parent], help="get a config value")
    config_get.add_argument("key", help="dotted key path (e.g., provider.service)")
    config_set = config_sub.add_parser("set", parents=[json_parent], help="set a config value")
    config_set.add_argument("key", help="dotted key path (e.g., provider.service)")
    config_set.add_argument("value", help="value to set")
    config_sub.add_parser("path", parents=[json_parent], help="show config file paths")

    # intro command
    intro_cmd = commands.add_parser("intro", parents=[json_parent], help="play the intro animation")
    intro_cmd.add_argument("--quick", action="store_true", help="short ~0.8s animation")
    intro_cmd.add_argument("--static", action="store_true", help="show only the static logo")
    intro_cmd.add_argument(
        "--tier", choices=["braille", "half", "ascii"], default=None, help="art tier"
    )

    # logo command
    logo_cmd = commands.add_parser("logo", parents=[json_parent], help="show the static logo")
    logo_cmd.add_argument(
        "--tier", choices=["braille", "half", "ascii"], default=None, help="art tier"
    )

    serve_cmd = commands.add_parser("serve", parents=[json_parent], help="run the local OpenAI-compatible gateway")
    serve_cmd.add_argument("--host", help="listen host (default from config)")
    serve_cmd.add_argument("--port", type=int, help="listen port (default from config)")
    serve_cmd.add_argument("--log-prompts", action="store_true", help="include context text in /cyrrus/last")

    # setup command
    setup_cmd = commands.add_parser("setup", parents=[json_parent], help="run the guided onboarding wizard")
    setup_cmd.add_argument("--port", type=int, default=8787, help="gateway port for snippets")
    setup_cmd.add_argument("--no-input", action="store_true", help="force non-interactive mode")
    setup_cmd.add_argument("--non-interactive", action="store_true", help="force non-interactive mode")
    setup_cmd.add_argument("--force", action="store_true", help="overwrite existing files without asking")
    setup_cmd.add_argument("--dry-run", action="store_true", help="show what would be written without writing")
    setup_cmd.add_argument("--plain", action="store_true", help="disable art, animation and colour")
    setup_cmd.add_argument("--goal", choices=["gateway", "library", "both"], help="how you will use Cyrrus")
    setup_cmd.add_argument("--service", help="service id (ollama, lmstudio, openai, ...)")
    setup_cmd.add_argument("--base-url", help="service base URL")
    setup_cmd.add_argument("--model", help="model name")
    setup_cmd.add_argument("--api-key-env", help="API key environment variable name")
    # Retain this hidden parser entry only to give a safe, actionable error.
    setup_cmd.add_argument("--api-key", dest="unsafe_api_key", help=argparse.SUPPRESS)
    setup_cmd.add_argument("--api-key-stdin", action="store_true", help="read an API key from standard input and save it only to .env")
    setup_cmd.add_argument("--memory-db", choices=["user", "project"], help="where to store facts")
    setup_cmd.add_argument("--retrieval", choices=["keyword", "hybrid"], help="retrieval strategy")
    setup_cmd.add_argument("--max-facts", type=int, help="max facts per session")
    setup_cmd.add_argument("--renderer", choices=["default", "compact"], help="context renderer")
    setup_cmd.add_argument("--max-context-tokens", type=int, help="context token budget")
    setup_cmd.add_argument("--starter-slide", choices=["assistant", "support", "coding", "discord", "none"], help="starter slide pack")
    setup_cmd.add_argument("--gateway-port", type=int, help="gateway port")
    setup_cmd.add_argument("--gateway-mode", choices=["inject", "manage"], help="gateway mode")
    setup_cmd.add_argument("--gateway-session", help="default gateway session")
    setup_cmd.add_argument("--scope", choices=["project", "user"], help="where to save config")
    setup_cmd.add_argument("--start-gateway", action="store_true", help="start the gateway after saving")
    setup_cmd.add_argument("--test-message", action="store_true", help="send a test message through the gateway")
    setup_cmd.add_argument("--skip-test", action="store_true", help="skip the connection test")

    setup_sub = setup_cmd.add_subparsers(dest="setup_action")
    show_cmd = setup_sub.add_parser("show", help="show an app snippet")
    show_cmd.add_argument("kind", choices=["zed", "python", "curl"], help="snippet kind")
    show_cmd.add_argument("--port", type=int, default=8787, help="gateway port for snippets")

    # home command
    home_cmd = commands.add_parser("home", parents=[json_parent], help="show the compact home menu")

    # logs command
    logs_cmd = commands.add_parser("logs", parents=[json_parent], help="print the last traces from a running gateway")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "json"):
        args.json = False
    if not hasattr(args, "config"):
        args.config = None
    if not hasattr(args, "db"):
        args.db = None
    if not hasattr(args, "session"):
        args.session = "default"
    if not hasattr(args, "yes"):
        args.yes = False

    if not args.command:
        # No command: guide a TTY user into setup or the home menu.  Protocol
        # and redirected-output invocations remain a help-only operation.
        config = load_config()
        if is_interactive():
            target = "setup" if (getattr(args, "tour", False) or not config.get("ui", {}).get("onboarded", False)) else "home"
            _entry_intro(args, config, "full" if target == "setup" else "quick")
            args.command = target
            if args.command == "setup":
                cmd_setup(args)
            else:
                cmd_home(args)
            return
        else:
            parser.print_help()
            print("\nStatus: Configure a service with 'cyrrus connect' to get started.")
            raise SystemExit(0)

    # Dispatch to command handler
    if args.command == "init":
        cmd_init(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "connect":
        cmd_connect(args)
    elif args.command == "services":
        cmd_services(args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "route":
        cmd_route(args)
    elif args.command == "memory":
        cmd_memory(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "intro":
        cmd_intro(args)
    elif args.command == "logo":
        cmd_logo(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "home":
        cmd_home(args)
    elif args.command == "logs":
        cmd_logs(args)
    else:
        parser.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
