"""
Fact extraction with three opt-in tiers.

Default (always available): regex patterns — zero dependencies.
cyrrus[facts-onnx]: ONNX GLiNER via onnxruntime (no torch) — catches
    natural phrasing the regex misses ("I go by Jordan", "call me J").
cyrrus[facts-torch]: full GLiNER via torch — highest accuracy, larger install.

extract_facts(text) keeps the same signature so Projector needs no changes.
Tier is chosen at runtime (onnx → torch → regex) unless configured explicitly:

    from cyrrus.extractor import configure_fact_extractor
    configure_fact_extractor("regex")   # force regex
    configure_fact_extractor("onnx")    # require onnx tier
    configure_fact_extractor("auto")    # default: detect from installed extras

Replace with your own async function for better recall:
    async def my_extractor(text: str) -> dict:
        ...
    bot = Projector(config, llm_call=my_llm, fact_extractor=my_extractor)
Disable entirely:
    bot = Projector(config, llm_call=my_llm, fact_extractor=None)
"""
from __future__ import annotations

import importlib.util
import logging
import re
from typing import Callable, Optional

log = logging.getLogger("cyrrus.extractor")

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

# Semantic NER labels → fact keys used by MemoryVault / Projector.
_GLINER_LABELS = [
    "person name",
    "job title",
    "workplace",
    "location",
    "project",
    "preference",
    "programming language",
]

_LABEL_TO_KEY = {
    "person name": "user_name",
    "name": "user_name",
    "job title": "user_job",
    "job": "user_job",
    "workplace": "user_workplace",
    "organization": "user_workplace",
    "company": "user_workplace",
    "location": "user_location",
    "project": "user_project",
    "project name": "user_project",
    "preference": "user_preference",
    "programming language": "user_language",
    "language": "user_language",
}

# Default HuggingFace model ids for each semantic tier.
_ONNX_MODEL_ID = "lmo3/gliner2-multi-v1-onnx"
_TORCH_MODEL_ID = "urchade/gliner_medium-v2.1"
_SEMANTIC_THRESHOLD = 0.4

# Explicit tier: None / "auto" means detect from installed packages.
_configured_tier: Optional[str] = None

# Lazily loaded model handles (or False if load was attempted and failed).
_onnx_runtime = None
_torch_model = None
_onnx_load_failed = False
_torch_load_failed = False

# Test hooks — inject fake predictors so tests never download models.
_onnx_predict_override: Optional[Callable[[str], list]] = None
_torch_predict_override: Optional[Callable[[str], list]] = None
# Optional overrides for availability probes (None = use real import checks).
_probe_onnx_override: Optional[bool] = None
_probe_torch_override: Optional[bool] = None


def _is_garbage(value: str, *, key: str = "") -> bool:
    if not value:
        return True
    clean = value.strip().lower()
    # Short proper-name nicknames ("J") are valid for user_name only.
    min_len = 1 if key == "user_name" else _MIN_VALUE_LENGTH
    if len(clean) < min_len or len(clean) > _MAX_VALUE_LENGTH:
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

    # Project — stops at comma so "cyrrus, a library" extracts just "cyrrus"
    (r"i(?:'m| am) (?:building|working on|making|developing|creating)\s+([^,\n]{3,60}?)(?:[.,!?]|$)", "user_project"),
    (r"my (?:project|app|bot|library|tool|startup) is (?:called |named )?([^.,!?\n]{2,40})", "user_project"),

    # Preferences
    (r"i (?:prefer|always use|love using|like using)\s+([^.,!?\n]{3,50})", "user_preference"),
    (r"my (?:favorite|preferred)\s+\w+\s+is\s+([^.,!?\n]{2,40})", "user_preference"),

    # Language
    (r"i(?:'m| am) (?:learning|using|coding in|writing in)\s+(python|javascript|typescript|rust|go|java|kotlin|swift|c\+\+|ruby|php|elixir)", "user_language"),
]


def configure_fact_extractor(tier: Optional[str] = "auto") -> None:
    """
    Force which fact-extraction tier to use.

    tier:
      - "auto" / None — detect from installed extras (default)
      - "regex" — always use the zero-dependency regex extractor
      - "onnx"  — use the ONNX / onnxruntime tier (requires cyrrus[facts-onnx])
      - "torch" — use the torch / GLiNER tier (requires cyrrus[facts-torch])

    Resets cached model handles so the next extract_facts() call re-resolves.
    """
    global _configured_tier
    if tier in (None, "auto"):
        _configured_tier = None
    elif tier in ("regex", "onnx", "torch"):
        _configured_tier = tier
    else:
        raise ValueError(
            f"Unknown fact extractor tier {tier!r}. "
            "Use 'auto', 'regex', 'onnx', or 'torch'."
        )
    reset_fact_extractor_cache()


def reset_fact_extractor_cache() -> None:
    """Drop lazily loaded models so the next call reloads (or re-probes)."""
    global _onnx_runtime, _torch_model, _onnx_load_failed, _torch_load_failed
    _onnx_runtime = None
    _torch_model = None
    _onnx_load_failed = False
    _torch_load_failed = False


def _reset_for_tests() -> None:
    """Full test reset: cache, overrides, and tier configuration."""
    global _onnx_predict_override, _torch_predict_override
    global _probe_onnx_override, _probe_torch_override, _configured_tier
    reset_fact_extractor_cache()
    _onnx_predict_override = None
    _torch_predict_override = None
    _probe_onnx_override = None
    _probe_torch_override = None
    _configured_tier = None


def _onnx_extra_available() -> bool:
    if _probe_onnx_override is not None:
        return _probe_onnx_override
    # facts-onnx installs onnxruntime; gliner2-onnx is the inference backend.
    if importlib.util.find_spec("onnxruntime") is None:
        return False
    if _onnx_predict_override is not None:
        return True
    return importlib.util.find_spec("gliner2_onnx") is not None


def _torch_extra_available() -> bool:
    if _probe_torch_override is not None:
        return _probe_torch_override
    if _torch_predict_override is not None:
        return True
    return importlib.util.find_spec("gliner") is not None


def get_fact_extractor_tier() -> str:
    """
    Return the tier that extract_facts() will use right now:
    'onnx', 'torch', or 'regex'.
    """
    if _configured_tier == "regex":
        return "regex"
    if _configured_tier == "onnx":
        return "onnx"
    if _configured_tier == "torch":
        return "torch"
    # auto: prefer onnx extra, then torch extra, then regex
    if _onnx_extra_available():
        return "onnx"
    if _torch_extra_available():
        return "torch"
    return "regex"


async def _extract_facts_regex(text: str) -> dict:
    """Zero-dependency regex extractor (original behavior)."""
    facts = {}
    for pattern, key in _PATTERNS:
        if key in facts:
            continue
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".,!?").strip()
            # Regex path keeps the original length floor (no short-name exception).
            if not _is_garbage(val):
                facts[key] = val
    return facts


def _entities_to_facts(entities) -> dict:
    """
    Convert GLiNER-style entity hits into {fact_key: value}.
    Accepts list[dict] with text/label/score, or objects with those attrs.
    First non-garbage hit per fact key wins (highest score preferred).
    """
    ranked = []
    for ent in entities or []:
        if isinstance(ent, dict):
            label = ent.get("label") or ent.get("entity") or ""
            text = ent.get("text") or ent.get("span") or ""
            score = float(ent.get("score", 1.0) or 0.0)
        else:
            label = getattr(ent, "label", "") or ""
            text = getattr(ent, "text", "") or ""
            score = float(getattr(ent, "score", 1.0) or 0.0)
        if score < _SEMANTIC_THRESHOLD:
            continue
        key = _LABEL_TO_KEY.get(str(label).strip().lower())
        if not key:
            continue
        val = str(text).strip().rstrip(".,!?").strip()
        if _is_garbage(val, key=key):
            continue
        ranked.append((score, key, val))

    ranked.sort(key=lambda row: row[0], reverse=True)
    facts = {}
    for _, key, val in ranked:
        if key not in facts:
            facts[key] = val
    return facts


def _load_onnx_runtime():
    global _onnx_runtime, _onnx_load_failed
    if _onnx_load_failed:
        return None
    if _onnx_runtime is not None:
        return _onnx_runtime
    try:
        from gliner2_onnx import GLiNER2ONNXRuntime
        _onnx_runtime = GLiNER2ONNXRuntime.from_pretrained(_ONNX_MODEL_ID)
        log.info("Fact extractor: ONNX GLiNER ready (%s).", _ONNX_MODEL_ID)
        return _onnx_runtime
    except Exception as e:
        _onnx_load_failed = True
        log.warning(
            "ONNX fact extractor failed to load (%s) — falling back to regex. "
            "Install with: pip install cyrrus[facts-onnx]",
            e,
        )
        return None


def _load_torch_model():
    global _torch_model, _torch_load_failed
    if _torch_load_failed:
        return None
    if _torch_model is not None:
        return _torch_model
    try:
        from gliner import GLiNER
        _torch_model = GLiNER.from_pretrained(_TORCH_MODEL_ID)
        log.info("Fact extractor: torch GLiNER ready (%s).", _TORCH_MODEL_ID)
        return _torch_model
    except Exception as e:
        _torch_load_failed = True
        log.warning(
            "Torch fact extractor failed to load (%s) — falling back to regex. "
            "Install with: pip install cyrrus[facts-torch]",
            e,
        )
        return None


def _predict_onnx_entities(text: str) -> Optional[list]:
    """Return entity list, or None if the ONNX backend is unavailable."""
    if _onnx_predict_override is not None:
        return _onnx_predict_override(text)
    runtime = _load_onnx_runtime()
    if runtime is None:
        return None
    try:
        return runtime.extract_entities(text, list(_GLINER_LABELS))
    except Exception as e:
        log.warning("ONNX fact extraction failed (%s) — falling back to regex.", e)
        return None


def _predict_torch_entities(text: str) -> Optional[list]:
    """Return entity list, or None if the torch backend is unavailable."""
    if _torch_predict_override is not None:
        return _torch_predict_override(text)
    model = _load_torch_model()
    if model is None:
        return None
    try:
        return model.predict_entities(
            text, list(_GLINER_LABELS), threshold=_SEMANTIC_THRESHOLD
        )
    except Exception as e:
        log.warning("Torch fact extraction failed (%s) — falling back to regex.", e)
        return None


async def extract_facts(text: str) -> dict:
    """
    Returns {fact_key: value} for facts found in text.
    Returns {} if nothing matched or input is invalid.
    Never raises.

    Uses onnx → torch → regex based on what's installed, unless
    configure_fact_extractor() pinned a specific tier.
    """
    if not text or not isinstance(text, str):
        return {}

    try:
        tier = get_fact_extractor_tier()

        if tier == "onnx":
            entities = _predict_onnx_entities(text)
            if entities is not None:
                return _entities_to_facts(entities)
            # Backend missing/broken: fall through to regex unless forced.
            if _configured_tier == "onnx":
                return {}

        elif tier == "torch":
            entities = _predict_torch_entities(text)
            if entities is not None:
                return _entities_to_facts(entities)
            if _configured_tier == "torch":
                return {}

        return await _extract_facts_regex(text)
    except Exception as e:
        log.warning("extract_facts failed (%s) — returning {}.", e)
        return {}
