"""
Tests for three audit bugs — kept minimal and scoped.

Bug 1: Anthropic _split_system wipeout
Bug 2: Multi-word triggers non-functional
Bug 3: BM25 threshold injects irrelevant facts
"""
import asyncio
import pytest
from cyrrus.providers import _split_system
from cyrrus.router import IntentRouter
from cyrrus.memory import MemoryVault


# ─── Bug 1 ───────────────────────────────────────────────────────────────

def test_split_system_concatenates_multiple_system_messages_in_order():
    persona = "You are a helpful assistant. Core persona."
    history_summary = "Previously mentioned: user likes cats."
    messages = [
        {"role": "system", "content": persona},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": history_summary},
        {"role": "assistant", "content": "hello"},
    ]
    system, filtered = _split_system(messages)
    # Both parts must be present, in order
    assert persona in system
    assert history_summary in system
    assert system.index(persona) < system.index(history_summary)
    # Only non-system messages remain
    assert all(m["role"] != "system" for m in filtered)
    assert len(filtered) == 2


def test_split_system_single_and_empty():
    # Single system message still works
    system, filtered = _split_system([{"role": "system", "content": "A"}, {"role": "user", "content": "hi"}])
    assert system == "A"
    # No system messages
    system, filtered = _split_system([{"role": "user", "content": "hi"}])
    assert system == ""


# ─── Bug 2 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_word_trigger_matches_phrase():
    router = IntentRouter({
        "core_lamp": {"content": "x"},
        "refund_policy": {"content": "R", "triggers": ["refund", "return", "money back"]},
    })
    slides, neg = await router.route("I want my money back")
    assert any(s.id == "refund_policy" for s in slides)


@pytest.mark.asyncio
async def test_multi_word_trigger_negation():
    router = IntentRouter({
        "core_lamp": {"content": "x"},
        "refund_policy": {"content": "R", "triggers": ["refund", "return", "money back"]},
    })
    slides, neg = await router.route("I don't want my money back")
    # Should NOT match as positive, should be in negated set
    assert not any(s.id == "refund_policy" for s in slides)
    assert "refund_policy" in neg


@pytest.mark.asyncio
async def test_single_word_trigger_still_works_after_phrase_fix():
    router = IntentRouter({
        "core_lamp": {"content": "x"},
        "refund_policy": {"content": "R", "triggers": ["refund", "return", "money back"]},
    })
    slides, _ = await router.route("I want a refund")
    assert any(s.id == "refund_policy" for s in slides)


# ─── Bug 3 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bm25_irrelevant_query_returns_empty():
    memory = MemoryVault(db_path=":memory:")
    await memory.upsert("s", "name", "Alice", 2)
    res = await memory.retrieve("s", "tell me a joke about bananas", limit=3)
    # No lexical overlap -> should return empty, not the irrelevant fact
    assert res == []


@pytest.mark.asyncio
async def test_bm25_relevant_query_still_retrieves():
    memory = MemoryVault(db_path=":memory:")
    await memory.upsert("s", "user_project", "cyrrus", 2)
    # Direct relevant query
    res = await memory.retrieve("s", "what is my project", limit=3)
    assert len(res) >= 1
    assert any("cyrrus" in s.content for s in res)

    # Also test that non-zero scoring still works via existing BM25 helper
    from cyrrus.bm25 import bm25_rank_facts
    facts = [("proj", "Python LLM library cyrrus", 3), ("food", "Italian tomato pasta sauce", 3)]
    ranked = bm25_rank_facts(facts, "Python LLM project", limit=3)
    assert ranked[0][1] == "proj"
    assert all(score > 0 for score, _, _, _ in ranked)
