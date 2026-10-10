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
