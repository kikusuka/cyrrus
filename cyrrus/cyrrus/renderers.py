def compact(data: dict) -> str:
    """Render a terse system message from slide state.

    Expected *data* dict (produced by Projector._render_system):
        {
            "slides": [...],         # non-memory slides
            "ghosts": [...],         # ghost slides
            "facts": [...],          # memory fact slides
            "base_system": str,      # lamp / system prompt content
        }

    Output: the base_system text first, always unchanged; then a blank line;
    then ``"Known facts about the user: key=value; key=value"``. With no
    facts, output only base_system.

    Fact keys are read from the slide id (strip the ``mem_`` prefix) and
    values from the slide content (strip the ``Fact: `` prefix).
    """
    base_system = data.get("base_system", "") or ""
    facts = data.get("facts", []) or []
    pairs = []
    for slide in facts:
        key = getattr(slide, "id", "") or ""
        if key.startswith("mem_"):
            key = key[len("mem_"):]
        content = getattr(slide, "content", "") or ""
        if content.startswith("Fact: "):
            content = content[len("Fact: "):]
        key = key.strip()
        content = content.strip()
        if key and content:
            pairs.append(f"{key}={content}")
    if pairs:
        return f"{base_system}\n\nKnown facts about the user: " + "; ".join(pairs)
    return base_system
