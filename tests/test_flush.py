import pytest
import asyncio
from cyrrus import Projector


@pytest.mark.asyncio
async def test_flush_awaits_background_extraction(tmp_path):
    """
    Test that flush() waits for background fact extraction to complete.
    Facts from the last turn should be stored after calling flush().
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    extracted = []

    async def slow_extractor(text):
        # Simulate slow extraction
        await asyncio.sleep(0.1)
        extracted.append(text)
        return {"user_name": "TestUser"}

    async def llm(messages):
        return "ok"

    bot = Projector(
        config,
        llm_call=llm,
        fact_extractor=slow_extractor,
        memory_db_path=str(tmp_path / "flush_test.db"),
    )

    # Process a message - extraction runs in background
    await bot.process("my name is TestUser", session_id="flush_test")
    
    # Extraction should still be pending
    assert len(extracted) == 0, "Extraction should not have completed yet"

    # Flush should wait for extraction
    await bot.flush()
    
    # Now extraction should be complete
    assert len(extracted) == 1, "Extraction should have completed after flush"
    assert extracted[0] == "my name is TestUser"

    # Verify fact was stored
    from cyrrus.sqlite_backend import get_backend
    backend = get_backend(str(tmp_path / "flush_test.db"))
    await backend.init_db()
    rows = await backend.retrieve_current("flush_test", limit=10)
    assert len(rows) == 1, "Fact should be stored in database"
    assert rows[0] == ("user_name", "TestUser", 1)


@pytest.mark.asyncio
async def test_async_context_manager(tmp_path):
    """
    Test that async with Projector(...) calls aclose() on exit.
    """
    config = {
        "core_lamp": {"content": "You are helpful."},
    }
    extracted = []

    async def slow_extractor(text):
        await asyncio.sleep(0.1)
        extracted.append(text)
        return {"user_name": "TestUser"}

    async def llm(messages):
        return "ok"

    async with Projector(
        config,
        llm_call=llm,
        fact_extractor=slow_extractor,
        memory_db_path=str(tmp_path / "context_test.db"),
    ) as bot:
        await bot.process("my name is TestUser", session_id="context_test")
        # Extraction should still be pending
        assert len(extracted) == 0

    # After exiting context, extraction should be complete
    assert len(extracted) == 1
    assert extracted[0] == "my name is TestUser"
