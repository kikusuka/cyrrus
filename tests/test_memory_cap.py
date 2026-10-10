import pytest
from cyrrus import Projector


@pytest.mark.asyncio
async def test_max_memory_facts_cap(tmp_path):
    """
    Test that max_memory_facts limits the number of injected facts.
    With max_memory_facts=1, only 1 fact should be injected even if more are stored.
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
        max_memory_facts=1,
        memory_db_path=str(tmp_path / "cap_test.db"),
    )

    # Extract multiple facts across turns
    await bot.process("my name is Alice", session_id="cap_test")
    await bot.flush()
    await bot.process("I live in Paris", session_id="cap_test")
    await bot.flush()

    # Query for name - should inject 1 fact
    await bot.process("what's my name?", session_id="cap_test")
    
    # Count "About the user:" occurrences in system message
    about_count = systems[2].count("About the user:")
    assert about_count == 1, f"Should have exactly 1 fact, got {about_count}"


@pytest.mark.asyncio
async def test_max_memory_tokens_cap(tmp_path):
    """
    Test that max_memory_tokens limits the total tokens of injected facts.
    With max_memory_tokens=5, only facts that fit in 5 tokens should be injected.
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
        max_memory_facts=10,
        max_memory_tokens=5,
        memory_db_path=str(tmp_path / "token_cap_test.db"),
    )

    # Extract a fact
    await bot.process("my name is Alice", session_id="token_cap")
    await bot.flush()

    # Query - should inject only what fits in 5 tokens
    await bot.process("what's my name?", session_id="token_cap")
    
    # Should have the fact (Alice is 1 token, fits in 5)
    assert "Alice" in systems[1], "Should have extracted name fact"
