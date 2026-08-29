"""
Validates and normalizes a slides config at startup.
Blows up immediately with a clear message on bad input —
better than a cryptic KeyError three hours into testing.

Tokens and priority are optional — if missing, they're computed
or defaulted automatically so minimal configs actually work:

    config = {
        "core_lamp": {"content": "You are helpful."},
        "code_lens": {"content": "Output only code.", "triggers": ["code"]},
    }
"""


class ConfigError(ValueError):
    pass


def _count_tokens(text: str) -> int:
    return max(1, len(text.split()))


def validate_config(config: dict) -> dict:
    """
    Validates and fills in defaults. Returns the normalized config
    (tokens and priority filled in where missing). Raises ConfigError
    with a specific message on the first problem found.
    """
    if not isinstance(config, dict):
        raise ConfigError(f"Config must be a dict, got {type(config).__name__}.")
    if not config:
        raise ConfigError("Config is empty — needs at least a 'core_lamp' entry.")
    if "core_lamp" not in config:
        raise ConfigError("Config is missing 'core_lamp'.")

    normalized = {}
    for slide_id, data in config.items():
        if slide_id.startswith("_"):
            if not isinstance(data, dict):
                raise ConfigError(f"Config metadata '{slide_id}' must be a dict.")
            normalized[slide_id] = dict(data)
            continue
        normalized[slide_id] = _normalize_entry(
            slide_id, data, is_lamp=(slide_id == "core_lamp")
        )

    trigger_slides = {}
    for slide_id, data in normalized.items():
        if slide_id == "core_lamp" or slide_id.startswith("_"):
            continue
        for trigger in data.get("triggers", []):
            key = trigger.casefold()
            trigger_slides.setdefault(key, []).append(slide_id)
    duplicates = {
        trigger: slide_ids
        for trigger, slide_ids in trigger_slides.items()
        if len(set(slide_ids)) > 1
    }
    if duplicates:
        trigger, slide_ids = next(iter(duplicates.items()))
        ids = ", ".join(dict.fromkeys(slide_ids))
        raise ConfigError(
            f"Duplicate trigger {trigger!r} appears in multiple slides: {ids}. "
            "Each trigger must belong to only one slide."
        )

    return normalized


def _normalize_entry(slide_id: str, data, is_lamp: bool) -> dict:
    label = "core_lamp" if is_lamp else f"slide '{slide_id}'"

    if not isinstance(data, dict):
        raise ConfigError(f"{label} must be a dict, got {type(data).__name__}.")

    if "content" not in data:
        raise ConfigError(f"{label} is missing required field 'content'.")
    if not isinstance(data["content"], str):
        raise ConfigError(
            f"{label}: 'content' must be a string, "
            f"got {type(data['content']).__name__}."
        )

    out = dict(data)

    # Auto-compute tokens from content if not specified.
    # User-specified value is taken as-is (they may have a reason).
    if "tokens" not in out:
        out["tokens"] = _count_tokens(out["content"])
    elif not isinstance(out["tokens"], (int, float)):
        raise ConfigError(
            f"{label}: 'tokens' must be a number, "
            f"got {type(out['tokens']).__name__} ({out['tokens']!r})."
        )

    # Priority defaults: lamp always wins, lenses/tools get 500.
    if "priority" not in out:
        out["priority"] = 1000 if is_lamp else 500
    elif not isinstance(out["priority"], (int, float)):
        raise ConfigError(
            f"{label}: 'priority' must be a number, "
            f"got {type(out['priority']).__name__} ({out['priority']!r})."
        )

    if not is_lamp:
        if out.get("type") == "tool" and not out.get("handler"):
            raise ConfigError(
                f"{label} is type 'tool' but has no 'handler'. "
                f"Add a handler name matching a key in tool_executors."
            )
        if out.get("handler") and out.get("type") != "tool":
            raise ConfigError(
                f"{label} has a 'handler' but type is {out.get('type')!r}, not 'tool'."
            )
        for field in ("triggers", "examples"):
            if field in out:
                if not isinstance(out[field], list) or not all(
                    isinstance(t, str) for t in out[field]
                ):
                    raise ConfigError(f"{label}: '{field}' must be a list of strings.")

        # Per-slide TTL — optional, must be a positive int if set
        if "active_turns" in out:
            if not isinstance(out["active_turns"], int) or out["active_turns"] < 1:
                raise ConfigError(
                    f"{label}: 'active_turns' must be a positive integer, "
                    f"got {out['active_turns']!r}."
                )

        # Tool output budget estimate — optional, defaults handled in Slide dataclass
        if "tool_estimate_tokens" in out:
            if not isinstance(out["tool_estimate_tokens"], (int, float)) or out["tool_estimate_tokens"] < 0:
                raise ConfigError(
                    f"{label}: 'tool_estimate_tokens' must be a non-negative number."
                )

    return out
