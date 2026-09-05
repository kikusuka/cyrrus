"""
Tests for tiered fact extraction.

Confirms:
- regex fallback still works with zero semantic deps (and when forced)
- tier selection picks onnx → torch → regex based on what's "installed"
- extract_facts() signature / Projector wiring stay unchanged
- semantic path can catch natural phrasing regex misses (via fake predictors)

No real model downloads — predictors and availability probes are injected.
"""
import pytest

from cyrrus.extractor import (
    _entities_to_facts,
    _extract_facts_regex,
    _reset_for_tests,
    configure_fact_extractor,
    extract_facts,
    get_fact_extractor_tier,
)
import cyrrus.extractor as ex


@pytest.fixture(autouse=True)
def _clean_extractor_state():
    _reset_for_tests()
    yield
    _reset_for_tests()


# ─── regex fallback (zero deps) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_regex_still_extracts_classic_phrases():
    configure_fact_extractor("regex")
    assert get_fact_extractor_tier() == "regex"

    facts = await extract_facts("my name is Muratha")
    assert facts.get("user_name") == "Muratha"

    facts = await extract_facts("I'm building cyrrus")
    assert "cyrrus" in facts.get("user_project", "").lower()

    facts = await extract_facts("I work at Google")
    assert "Google" in facts.get("user_workplace", "")


@pytest.mark.asyncio
async def test_regex_returns_empty_on_garbage_and_none():
    configure_fact_extractor("regex")
    assert await extract_facts("hello how are you") == {}
    assert await extract_facts(None) == {}
    assert await extract_facts("") == {}
    assert await extract_facts(123) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_regex_misses_natural_phrasing():
    """Documents why the semantic tiers exist — regex is rigid."""
    configure_fact_extractor("regex")
    assert await extract_facts("I go by Jordan") == {}
    assert await extract_facts("you can call me J") == {}


# ─── tier selection ──────────────────────────────────────────────────────────

def test_tier_defaults_to_regex_when_no_extras():
    ex._probe_onnx_override = False
    ex._probe_torch_override = False
    configure_fact_extractor("auto")
    assert get_fact_extractor_tier() == "regex"


def test_tier_prefers_onnx_over_torch():
    ex._probe_onnx_override = True
    ex._probe_torch_override = True
    configure_fact_extractor("auto")
    assert get_fact_extractor_tier() == "onnx"


def test_tier_uses_torch_when_onnx_absent():
    ex._probe_onnx_override = False
    ex._probe_torch_override = True
    configure_fact_extractor("auto")
    assert get_fact_extractor_tier() == "torch"


def test_explicit_tier_overrides_installed_extras():
    ex._probe_onnx_override = True
    ex._probe_torch_override = True
    configure_fact_extractor("regex")
    assert get_fact_extractor_tier() == "regex"
    configure_fact_extractor("torch")
    assert get_fact_extractor_tier() == "torch"
    configure_fact_extractor("onnx")
    assert get_fact_extractor_tier() == "onnx"


def test_configure_rejects_unknown_tier():
    with pytest.raises(ValueError, match="Unknown fact extractor tier"):
        configure_fact_extractor("magic")


# ─── semantic path via injected predictors ───────────────────────────────────

@pytest.mark.asyncio
async def test_onnx_tier_catches_natural_phrasing():
    ex._probe_onnx_override = True
    ex._onnx_predict_override = lambda text: [
        {"text": "Jordan", "label": "person name", "score": 0.92},
    ]
    configure_fact_extractor("auto")
    assert get_fact_extractor_tier() == "onnx"

    facts = await extract_facts("I go by Jordan")
    assert facts == {"user_name": "Jordan"}


@pytest.mark.asyncio
async def test_onnx_allows_short_nickname():
    ex._probe_onnx_override = True
    ex._onnx_predict_override = lambda text: [
        {"text": "J", "label": "person name", "score": 0.88},
    ]
    configure_fact_extractor("onnx")
    facts = await extract_facts("you can call me J")
    assert facts == {"user_name": "J"}


@pytest.mark.asyncio
async def test_torch_tier_used_when_selected():
    ex._probe_onnx_override = False
    ex._probe_torch_override = True
    ex._torch_predict_override = lambda text: [
        {"text": "indie developer", "label": "job title", "score": 0.81},
    ]
    configure_fact_extractor("auto")
    assert get_fact_extractor_tier() == "torch"

    facts = await extract_facts("I earn my keep as an indie developer these days")
    assert facts == {"user_job": "indie developer"}


@pytest.mark.asyncio
async def test_onnx_backend_failure_falls_back_to_regex_in_auto_mode():
    """If onnx is selected but predictor returns None, auto mode uses regex."""
    ex._probe_onnx_override = True
    ex._onnx_predict_override = lambda _text: None
    configure_fact_extractor("auto")
    facts = await extract_facts("my name is Muratha")
    assert facts.get("user_name") == "Muratha"


@pytest.mark.asyncio
async def test_forced_onnx_with_dead_backend_returns_empty_not_regex():
    ex._probe_onnx_override = True
    ex._onnx_predict_override = lambda _text: None
    configure_fact_extractor("onnx")
    facts = await extract_facts("my name is Muratha")
    assert facts == {}


# ─── entity mapping helper ───────────────────────────────────────────────────

def test_entities_to_facts_maps_labels_and_filters_garbage():
    facts = _entities_to_facts([
        {"text": "Alice", "label": "person name", "score": 0.9},
        {"text": "something", "label": "preference", "score": 0.95},  # garbage
        {"text": "Paris", "label": "location", "score": 0.2},  # below threshold
        {"text": "cyrrus", "label": "project", "score": 0.7},
    ])
    assert facts == {"user_name": "Alice", "user_project": "cyrrus"}


@pytest.mark.asyncio
async def test_direct_regex_helper_unchanged():
    facts = await _extract_facts_regex("I live in Hyderabad")
    assert facts.get("user_location") == "Hyderabad"
