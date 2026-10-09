import pytest
from cyrrus import Projector


@pytest.mark.asyncio
async def test_memory_facts_injected_into_system_message(tmp_path):
    """
    Test that memory facts are injected into the system message.
    
    Turn 1: "my name is Alice" - should extract and store the fact
    Turn 2: "what's my name?" - system message should contain "Alice"
    Turn 3: "tell me a joke about bananas" - system message should NOT contain "Alice"
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
        memory_db_path=str(tmp_path / "memory_injection.db"),
    )

    # Turn 1: extract fact
    await bot.process("my name is Alice", session_id="memory_test")
    # Wait for shadow extraction to complete
    import asyncio
    await asyncio.sleep(0.2)

    # Turn 2: query that should retrieve the fact
    await bot.process("what's my name?", session_id="memory_test")
    assert "Alice" in systems[1], "Turn 2: system message should contain Alice"

    # Turn 3: unrelated query - should not retrieve the fact
    await bot.process("tell me a joke about bananas", session_id="memory_test")
    assert "Alice" not in systems[2], "Turn 3: system message should NOT contain Alice (unrelated query)"
