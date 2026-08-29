"""
Default fact extractor. Pulls structured facts from conversation
using regex patterns — no LLM call, no extra dependencies.

Runs on both user messages and assistant responses automatically.
Facts from uncertain responses (hedged with "I think", "probably",
etc.) are skipped before they reach here.

Replace with your own async function for better recall:
    async def my_extractor(text: str) -> dict:
        ...
    bot = Projector(config, llm_call=my_llm, fact_extractor=my_extractor)
Disable entirely:
    bot = Projector(config, llm_call=my_llm, fact_extractor=None)
"""
import re

# Values that are too vague to be worth storing.
_GARBAGE_VALUES = {
    "myself", "yourself", "himself", "herself", "itself", "themselves",
    "something", "anything", "everything", "nothing", "someone", "anyone",
    "somewhere", "anywhere", "sometime", "always", "never", "maybe",
    "stuff", "things", "it", "this", "that", "here", "there",
    "a lot", "a bit", "a little", "some", "many", "few",
    "great", "good", "bad", "better", "best", "worse", "worst",
    "something great", "something cool", "something new", "something big",
}

# Minimum character length for a stored value to be meaningful.
_MIN_VALUE_LENGTH = 3
_MAX_VALUE_LENGTH = 80


def _is_garbage(value: str) -> bool:
    if not value:
        return True
    clean = value.strip().lower()
    if len(clean) < _MIN_VALUE_LENGTH or len(clean) > _MAX_VALUE_LENGTH:
        return True
    if clean in _GARBAGE_VALUES:
        return True
    # Pure numbers aren't useful as standalone facts
    if re.match(r"^\d+$", clean):
        return True
    return False


_PATTERNS = [
    # Name — prefix matched case-insensitively, value must be properly capitalized
    (r"(?i:(?:my name is|call me)\s+)([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20})?)", "user_name"),

    # Job — specific job title words only
    (r"i(?:'m| am) (?:a |an )?(\w+(?:\s+\w+)?\s+(?:developer|engineer|designer|student|researcher|founder|freelancer|architect|scientist|analyst|manager|writer|teacher|doctor|lawyer|nurse))", "user_job"),

    # Workplace
    (r"i work (?:at|for)\s+([^.,!?\n]{3,50})", "user_workplace"),

    # Location
    (r"i(?:'m| am) (?:from|in|based in)\s+([A-Z][a-zA-Z\s]{2,30}?)(?:[.,!?]|$)", "user_location"),
    (r"i live in\s+([A-Z][a-zA-Z\s]{2,30}?)(?:[.,!?]|$)", "user_location"),

    # Project — stops at comma so "slid3s, a library" extracts just "slid3s"
    (r"i(?:'m| am) (?:building|working on|making|developing|creating)\s+([^,\n]{3,60}?)(?:[.,!?]|$)", "user_project"),
    (r"my (?:project|app|bot|library|tool|startup) is (?:called |named )?([^.,!?\n]{2,40})", "user_project"),

    # Preferences
    (r"i (?:prefer|always use|love using|like using)\s+([^.,!?\n]{3,50})", "user_preference"),
    (r"my (?:favorite|preferred)\s+\w+\s+is\s+([^.,!?\n]{2,40})", "user_preference"),

    # Language
    (r"i(?:'m| am) (?:learning|using|coding in|writing in)\s+(python|javascript|typescript|rust|go|java|kotlin|swift|c\+\+|ruby|php|elixir)", "user_language"),
]


async def extract_facts(text: str) -> dict:
    """
    Returns {fact_key: value} for facts found in text.
    Returns {} if nothing matched or input is invalid.
    Never raises.
    """
    if not text or not isinstance(text, str):
        return {}

    facts = {}
    for pattern, key in _PATTERNS:
        if key in facts:
            continue
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".,!?").strip()
            if not _is_garbage(val):
                facts[key] = val

    return facts
