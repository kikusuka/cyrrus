"""Interactive command-line tools for cyrrus."""

import argparse
import json
import sys
from typing import Optional, Sequence

from .templates import (
    PERSONALITIES,
    TEMPLATES,
    get_template_config,
    list_personalities,
    list_templates,
    match_template,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a cyrrus slides.json config.")
    commands = parser.add_subparsers(dest="command")
    init = commands.add_parser("init", help="create a slides.json configuration")
    init.add_argument("--template", "-t", choices=list(TEMPLATES), help="bot template")
    init.add_argument("--tone", "--personality", dest="tone", help="personality/tone")
    init.add_argument("--output", "-o", default="slides.json", help="output path")
    init.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    init.add_argument("--no-input", action="store_true", help="force non-interactive mode")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command != "init":
        build_parser().print_help()
        raise SystemExit(2)

    non_interactive = args.no_input or args.yes or not is_interactive()
    if non_interactive:
        non_interactive_mode(args.template, args.tone, args.output)
    else:
        interactive_mode(args.template, args.tone, args.output)


if __name__ == "__main__":
    main()
