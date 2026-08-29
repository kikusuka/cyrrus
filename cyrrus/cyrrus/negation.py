import re

# Negation words we look for in the few words before a matched trigger.
# This is a heuristic — it catches the common cases like "don't search"
# and "without looking that up", not every possible phrasing.
NEGATION_WORDS = ["don't", "do not", "dont", "skip", "without", "never", "not"]
NEGATION_WINDOW = 4  # words to look back


def is_negated(lower_text: str, match_start: int) -> bool:
    """Returns True if a negation word appears in the few words before match_start."""
    preceding = lower_text[:match_start].split()
    window = " ".join(preceding[-NEGATION_WINDOW:])
    return any(re.search(rf"\b{re.escape(w)}\b", window) for w in NEGATION_WORDS)
