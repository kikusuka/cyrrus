import pytest
from cyrrus import Projector


@pytest.mark.asyncio
async def test_ghost_slides_expire_after_max_ghost_turns(tmp_path):
    """
    Test that ghost slides expire after max_ghost_turns.
    
    With max_active_turns=1, max_ghost_turns=2:
    - Turn 1: slide triggered (active, counter=0)
    - Turn 2: slide not triggered (still active, counter=1)
    - Turn 3: slide becomes ghost (age 0)
    - Turn 4: slide still ghost (age 1)
    - Turn 5: slide should be gone (age 2 expires)
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
        "refund_slide": {"content": "REFUND_RULES", "triggers": ["refund"]},
    }
    systems = []

    async def llm(messages):
        systems.append(messages[0]["content"])
        return "ok"

    async def no_facts(text):
        return {}

    bot = Projector(
        config,
        llm_call=llm,
        max_active_turns=1,
        max_ghost_turns=2,
        fact_extractor=no_facts,
        memory_db_path=str(tmp_path / "ghost_expiry.db"),
    )

    def has_slide(system, slide_content):
        return slide_content in system

    # Turn 1: trigger refund slide
    await bot.process("I need a refund", session_id="ghost_test")
    assert has_slide(systems[0], "REFUND_RULES"), "Turn 1: refund slide should be active"
    assert "fading" not in systems[0], "Turn 1: should not be ghost yet"

    # Turn 2: unrelated topic, still active (counter=1 <= max_active_turns=1)
    await bot.process("what's the weather", session_id="ghost_test")
    assert has_slide(systems[1], "REFUND_RULES"), "Turn 2: refund slide should still be active"
    assert "fading" not in systems[1], "Turn 2: should not be ghost yet"

    # Turn 3: becomes ghost (counter=2 > max_active_turns=1)
    await bot.process("tell me a joke", session_id="ghost_test")
    assert has_slide(systems[2], "REFUND_RULES"), "Turn 3: refund slide should be ghost"
    assert "fading" in systems[2], "Turn 3: should be ghost"

    # Turn 4: still ghost (age 1)
    await bot.process("how are you", session_id="ghost_test")
    assert has_slide(systems[3], "REFUND_RULES"), "Turn 4: refund slide should still be ghost"
    assert "fading" in systems[3], "Turn 4: should still be ghost"

    # Turn 5: should be fully gone (age 2 expires)
    await bot.process("goodbye", session_id="ghost_test")
    assert not has_slide(systems[4], "REFUND_RULES"), "Turn 5: refund slide should be gone"
