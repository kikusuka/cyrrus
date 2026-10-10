import pytest
from cyrrus import Projector


@pytest.mark.asyncio
async def test_fact_supersession_name(tmp_path):
    """
    Test that a new value for the same key supersedes the old one.
    "my name is Alice" then "my name is Bob" should leave only Bob injected.
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    systems = []

    async def llm(messages):
        systems.append(messages[0]["content"])
        return "ok"

    bot = Projector(
        config,
        llm_call=llm,
        memory_db_path=str(tmp_path / "supersession.db"),
    )

    # Turn 1: extract Alice
    await bot.process("my name is Alice", session_id="supersession")
    await bot.flush()  # Wait for extraction to complete

    # Turn 2: query - should have Alice
    await bot.process("what's my name?", session_id="supersession")
    assert "Alice" in systems[1], "Turn 2: should contain Alice"
    assert "Bob" not in systems[1], "Turn 2: should not contain Bob"

    # Turn 3: extract Bob (supersedes Alice)
    await bot.process("my name is Bob", session_id="supersession")
    await bot.flush()  # Wait for extraction to complete

    # Turn 4: query - should have Bob, not Alice
    await bot.process("what's my name?", session_id="supersession")
    assert "Bob" in systems[3], "Turn 4: should contain Bob"
    assert "Alice" not in systems[3], "Turn 4: should not contain Alice (superseded)"


@pytest.mark.asyncio
async def test_fact_supersession_location(tmp_path):
    """
    Test that location facts supersede correctly.
    "I live in Paris" then "I moved to Lisbon" should leave only Lisbon.
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    systems = []

    async def llm(messages):
        systems.append(messages[0]["content"])
        return "ok"

    bot = Projector(
        config,
        llm_call=llm,
        memory_db_path=str(tmp_path / "supersession_loc.db"),
    )

    # Turn 1: extract Paris
    await bot.process("I live in Paris", session_id="loc_test")
    import asyncio
    await bot.flush()  # Wait for extraction to complete

    # Verify Paris was stored
    from cyrrus.sqlite_backend import get_backend
    backend = get_backend(str(tmp_path / "supersession_loc.db"))
    await backend.init_db()
    rows = await backend.retrieve_current("loc_test", limit=10)
    assert len(rows) == 1, "Should have one fact"
    assert rows[0] == ("user_location", "Paris", 1), "Should be Paris"

    # Turn 2: extract Lisbon (supersedes Paris)
    await bot.process("I moved to Lisbon", session_id="loc_test")
    await bot.flush()  # Wait for extraction to complete

    # Verify only Lisbon is current
    rows = await backend.retrieve_current("loc_test", limit=10)
    assert len(rows) == 1, f"Should have one fact, got {rows}"
    assert rows[0] == ("user_location", "Lisbon", 1), f"Should be Lisbon, got {rows[0]}"

    # Verify Paris is superseded (exists in history but not current)
    history = await backend.get_fact_history("loc_test", "user_location")
    assert len(history) == 2, f"Should have two versions in history, got {len(history)}"
    # History is ordered by valid_at ASC, so oldest is first
    assert history[0]["value"] == "Paris", f"Oldest should be Paris, got {history[0]['value']}"
    assert history[1]["value"] == "Lisbon", f"Newest should be Lisbon, got {history[1]['value']}"
    assert history[0]["invalid_at"] is not None, "Paris should be marked invalid"

    # Turn 3: question-style retrieval "where do I live?" -> Lisbon only (exact original query)
    await bot.process("where do I live?", session_id="loc_test")
    turn3_sys = systems[2]
    assert "Lisbon" in turn3_sys, f"'where do I live?' -> should have Lisbon, got: {turn3_sys}"
    assert "Paris" not in turn3_sys, f"'where do I live?' -> should NOT have Paris (superseded)"


@pytest.mark.asyncio
async def test_key_aliases_question_queries(tmp_path):
    """
    KEY_ALIASES integration tests:
    - "what's my name?" -> name
    - "where do I work?" -> employer
    - "what do I like?" -> preference
    - "tell me a joke about bananas" -> no facts (threshold guard)
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    systems = []

    async def llm(messages):
        systems.append(messages[0]["content"])
        return "ok"

    bot = Projector(
        config,
        llm_call=llm,
        memory_db_path=str(tmp_path / "aliases.db"),
    )

    # Store all four facts
    await bot.process("my name is Alice Wonderland", session_id="alias_test")
    await bot.flush()
    await bot.process("I work at Acme Robotics", session_id="alias_test")
    await bot.flush()
    await bot.process("I like raspberry ice cream and sour candy", session_id="alias_test")
    await bot.flush()

    # Test 1: what's my name? -> Alice
    await bot.process("what's my name?", session_id="alias_test")
    assert "Alice" in systems[-1], f"name query should have Alice, got: {systems[-1][:500]}"

    # Test 2: where do I work? -> Acme
    await bot.process("where do I work?", session_id="alias_test")
    assert "Acme" in systems[-1], f"work/employer query should have Acme, got: {systems[-1][:500]}"

    # Test 3: what do I like? -> raspberry
    await bot.process("what do I like?", session_id="alias_test")
    assert "raspberry" in systems[-1], f"preference query should have raspberry, got: {systems[-1][:500]}"

    # Test 4: "tell me a joke about bananas" -> NO injected facts
    about_before_count = systems[-1].count("About the user:")
    await bot.process("tell me a joke about bananas", session_id="alias_test")
    about_after = systems[-1].count("About the user:")
    assert about_after == 0, (
        f"banana joke query should have 0 facts, count={about_after}, "
        f"sys: {systems[-1][:500]}"
    )
