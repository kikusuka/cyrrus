from cyrrus import Projector


async def test_topic_switch_ghost_and_return(tmp_path):
    config = {
        "core_lamp": {"content": "You are helpful."},
        "code_lens": {"content": "CODE_RULES", "triggers": ["code"]},
        "weather_lens": {"content": "WEATHER_RULES", "triggers": ["weather"]},
    }
    systems = []

    async def llm(messages):
        systems.append(messages[0]["content"])
        return "ok"

    async def no_facts(text):
        return {}

    bot = Projector(
        config, llm_call=llm, max_active_turns=1,
        fact_extractor=no_facts, memory_db_path=str(tmp_path / "topic.db"),
    )

    def line(system, marker):
        return next((l for l in system.splitlines() if marker in l), None)

    for msg in ["write some code", "what is the weather",
                "ok sounds good", "fix this code"]:
        await bot.process(msg, session_id="topic_switch")

    t1, t2, t3, t4 = systems

    assert line(t1, "CODE_RULES") and "fading" not in line(t1, "CODE_RULES")
    assert line(t1, "WEATHER_RULES") is None

    assert "fading" not in line(t2, "CODE_RULES")
    assert "fading" not in line(t2, "WEATHER_RULES")

    assert "fading" in line(t3, "CODE_RULES")       # coding is now a ghost
    assert "fading" not in line(t3, "WEATHER_RULES")

    assert "fading" not in line(t4, "CODE_RULES")   # resurrected, clean
    assert "fading" in line(t4, "WEATHER_RULES")    # weather faded in turn