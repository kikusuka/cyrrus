def compact(data: dict) -> str:
    """Render a terse system message from slide state.

    Expected *data* dict (produced by Projector._render_system):
        {
            "slides": [...],         # non‑memory slides
            "ghosts": [...],         # ghost slides
            "facts": [...],          # memory fact slides
            "base_system": str,      # lamp / system prompt content
        }

    The returned string is a compact representation, e.g.
    ``"facts: name=Alice; city=Lisbon"``.
    """
    lamp = data["base_system"]
    facts = data["facts"]
    # Collect "key=value" pairs from fact slide contents.
    pairs = []
    for slide in facts:
        # Strip any "About the user: " prefix that the default renderer
        # would have added; if the caller already stripped it, this is a no‑op.
        content = slide.content
        if content.startswith("About the user: "):
            content = content[len("About the user: "):]
        # Take the first "Fact: " prefix removal if present
        if content.startswith("Fact: "):
            content = content[len("Fact: "):]
        if content:
            pairs.append(f"{content.strip()}=")

    # Deduplicate by key, keep last value
    seen = {}
    for pair in pairs:
        if "=" in pair:
            key, val = pair.split("=", 1)
            seen[key.strip()] = val.strip()

    # Build "key=value; key=value" string
    parts = [f"{k}={v}" for k, v in seen.items()]
    if parts:
        return "facts: " + "; ".join(parts)
    return lamp