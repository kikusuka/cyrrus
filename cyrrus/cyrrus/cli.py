"""Interactive command-line tools for cyrrus."""

import argparse
import json
import sys
import os
from typing import Optional, Sequence
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
            status_symbol = "✓" if check["status"] == "ok" else ("!" if check["status"] == "warning" else "✗")
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
    config = load_config(project_dir=Path(args.config) if args.config else None)
    db_path = args.db or config.get("memory", {}).get("db_path")

    if args.action == "list":
        result = memory_list(db_path=db_path, limit=args.limit)
    elif args.action == "search":
        result = memory_search(args.query, db_path=db_path, limit=args.limit)
    elif args.action == "forget":
        if not args.yes:
            print("Error: --yes required for destructive operations", file=sys.stderr)
            raise SystemExit(1)
        result = memory_forget(args.fact_id, db_path=db_path)
    elif args.action == "forget-all":
        if not args.yes:
            print("Error: --yes required for destructive operations", file=sys.stderr)
            raise SystemExit(1)
        result = memory_forget_all(db_path=db_path)
    elif args.action == "export":
        result = memory_export(db_path=db_path, output_path=args.output)
    elif args.action == "import":
        result = memory_import(args.input, db_path=db_path)
    else:
        print(f"Error: Unknown action '{args.action}'", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            if args.action == "list":
                print(f"Facts ({len(result['facts'])}):")
                for fact in result["facts"]:
                    print(f"  [{fact['id']}] {fact['content'][:50]}...")
            elif args.action == "search":
                print(f"Results ({len(result['results'])}):")
                for r in result["results"]:
                    print(f"  - {r['content'][:50]}... (score: {r.get('score', 'N/A')})")
            elif args.action == "forget":
                print(f"Fact {args.fact_id} deleted" if result["deleted"] else "Delete failed")
            elif args.action == "forget-all":
                print(f"Deleted {result['count']} facts")
            elif args.action == "export":
                print(f"Exported {result['count']} facts to {result['output_path']}")
            elif args.action == "import":
                print(f"Imported {result['count']} facts")
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
            raise SystemExit(1)


def cmd_sessions(args) -> None:
    """List conversation sessions."""
    config = load_config(project_dir=Path(args.config) if args.config else None)
    db_path = args.db or config.get("memory", {}).get("db_path")

    result = sessions(db_path=db_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"Sessions ({len(result['sessions'])}):")
            for sess in result["sessions"]:
                print(f"  [{sess['id']}] {sess['created_at']} ({sess['message_count']} messages)")
        else:
            print(f"Error: {result['error']}", file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cyrrus context routing for LLM calls")
    parser.add_argument("--version", action="version", version="cyrrus 0.3.0b5")
    parser.add_argument("--config", help="path to project config file")
    parser.add_argument("--db", help="path to memory database")
    parser.add_argument("--session", help="session ID")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")

    commands = parser.add_subparsers(dest="command", help="Available commands")

    # init command (existing)
    init = commands.add_parser("init", help="create a slides.json configuration")
    init.add_argument("--template", "-t", choices=list(TEMPLATES), help="bot template")
    init.add_argument("--tone", "--personality", dest="tone", help="personality/tone")
    init.add_argument("--output", "-o", default="slides.json", help="output path")
    init.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    init.add_argument("--no-input", action="store_true", help="force non-interactive mode")

    # doctor command
    doctor_cmd = commands.add_parser("doctor", help="run diagnostic checks")

    # connect command
    connect = commands.add_parser("connect", help="configure and test service connection")
    connect.add_argument("--service", required=True, help="service ID")
    connect.add_argument("--model", help="model name")
    connect.add_argument("--base-url", help="override base URL")
    connect.add_argument("--api-key-env", help="API key environment variable name")
    connect.add_argument("--api-key", help="API key value (for .env)")
    connect.add_argument("--test", action="store_true", help="test connection")
    connect.add_argument("--save", choices=["project", "user"], help="save configuration")

    # services command
    services_cmd = commands.add_parser("services", help="list available services")

    # models command
    models = commands.add_parser("models", help="list models for a service")
    models.add_argument("--service", help="service ID (uses configured if not set)")
    models.add_argument("--base-url", help="override base URL")
    models.add_argument("--timeout", type=float, default=5.0, help="request timeout")

    # route command
    route = commands.add_parser("route", help="dry run of context routing")
    route.add_argument("text", help="input text to route")
    route.add_argument("--slides", help="path to slides.json")

    # memory command
    memory = commands.add_parser("memory", help="memory operations")
    memory_sub = memory.add_subparsers(dest="action", required=True)
    memory_list_cmd = memory_sub.add_parser("list", help="list facts")
    memory_list_cmd.add_argument("--limit", type=int, default=100, help="max facts to return")
    memory_search_cmd = memory_sub.add_parser("search", help="search facts")
    memory_search_cmd.add_argument("query", help="search query")
    memory_search_cmd.add_argument("--limit", type=int, default=10, help="max results")
    memory_forget_cmd = memory_sub.add_parser("forget", help="delete a fact")
    memory_forget_cmd.add_argument("fact_id", type=int, help="fact ID")
    memory_forget_cmd.add_argument("--yes", action="store_true", help="confirm deletion")
    memory_forget_all_cmd = memory_sub.add_parser("forget-all", help="delete all facts")
    memory_forget_all_cmd.add_argument("--yes", action="store_true", help="confirm deletion")
    memory_export_cmd = memory_sub.add_parser("export", help="export facts to JSON")
    memory_export_cmd.add_argument("--output", help="output file path")
    memory_import_cmd = memory_sub.add_parser("import", help="import facts from JSON")
    memory_import_cmd.add_argument("input", help="input file path")

    # sessions command
    sessions_cmd = commands.add_parser("sessions", help="list conversation sessions")

    # config command
    config_cmd = commands.add_parser("config", help="configuration operations")
    config_sub = config_cmd.add_subparsers(dest="action", required=True)
    config_sub.add_parser("show", help="show configuration (secrets redacted)")
    config_get = config_sub.add_parser("get", help="get a config value")
    config_get.add_argument("key", help="dotted key path (e.g., provider.service)")
    config_set = config_sub.add_parser("set", help="set a config value")
    config_set.add_argument("key", help="dotted key path (e.g., provider.service)")
    config_set.add_argument("value", help="value to set")
    config_sub.add_parser("path", help="show config file paths")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        # No command: print help and status
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
    else:
        parser.print_help()
        raise SystemExit(2)


if __name__ == "__main__":
    main()
