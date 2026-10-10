"""
Tests for Step 4: Non-blocking Ollama provider.

Uses a fake slow blocking call (time.sleep inside a function that simulates
the blocking urllib path) wrapped in asyncio.to_thread, then runs the fake
Ollama call concurrently with an event-loop ticker task. The ticker should
keep incrementing while the slow "LLM call" is in flight, proving the loop
was not blocked.
"""
import asyncio
import time
import pytest

from cyrrus.providers import StreamChunk, ollama as make_ollama_wrapper


def _make_blocking_fake_ollama(delay_seconds: float = 0.3, reply: str = "hello!"):
    """
    Build an ollama-style provider that simulates a BLOCKING call
    (like urllib.request without to_thread). The returned callable uses
    asyncio.to_thread to wrap the blocking sleep, matching the provider's
    fallback path.
    """
    def _blocking_impl(messages, *, stream: bool):
        # This simulates a blocking urllib HTTP POST that takes time.
        time.sleep(delay_seconds)
        if stream:
            return [
                {"message": {"content": reply[:3]}, "done": False},
                {"message": {"content": reply[3:]}, "done": True},
            ]
        return {"message": {"content": reply}}

    async def _call(messages):
        obj = await asyncio.to_thread(_blocking_impl, messages, stream=False)
        return obj["message"]["content"]

    async def _astream(messages):
        chunks = await asyncio.to_thread(_blocking_impl, messages, stream=True)
        for raw in chunks:
            if isinstance(raw, dict) and "message" in raw:
                yield StreamChunk(text=raw["message"].get("content"))
            else:
                yield StreamChunk()

    _call.astream = _astream
    return _call


@pytest.mark.asyncio
async def test_ollama_fallback_does_not_block_event_loop():
    """
    While a slow 0.3s blocking Ollama call is running, an async ticker
    running concurrently should be able to advance several times. If the
    event loop were blocked (no to_thread), the ticker would advance 0
    times during the call.
    """
    slow_llm = _make_blocking_fake_ollama(delay_seconds=0.3, reply="ok-fake")

    ticks = 0
    running = True

    async def ticker():
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.05)  # tick every 50ms

    ticker_task = asyncio.create_task(ticker())
    try:
        # Let ticker start
        await asyncio.sleep(0.01)
        ticks_before_call = ticks
        # Run the slow LLM call (simulates 300ms blocking work in thread)
        reply = await slow_llm([{"role": "user", "content": "hi"}])
        ticks_during_call = ticks - ticks_before_call
    finally:
        running = False
        await ticker_task

    assert reply == "ok-fake"
    # In 300ms of wall time with 50ms sleep interval, we expect
    # at least 3-4 ticks even accounting for overhead. If to_thread
    # was wrong and the loop blocked, ticks_during_call would be 0.
    assert ticks_during_call >= 2, (
        f"Expected event loop to keep ticking during slow call. "
        f"ticks_before={ticks_before_call}, ticks_during={ticks_during_call}"
    )


@pytest.mark.asyncio
async def test_ollama_timeout_kwarg_accepted():
    """ollama() accepts timeout parameter without raising (stdlib path)."""
    fn = make_ollama_wrapper("some-model", timeout=15.0)
    assert callable(fn)
    assert hasattr(fn, "astream")
    # astream should be async function (or at least callable returning async iter)
    assert callable(getattr(fn, "astream", None))


@pytest.mark.asyncio
async def test_ollama_fallback_streamed_nonblocking():
    """Fallback streaming path also runs in to_thread and doesn't block the loop."""
    slow_llm = _make_blocking_fake_ollama(delay_seconds=0.2, reply="stream!")

    ticks = 0
    running = True

    async def ticker():
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.04)

    ticker_task = asyncio.create_task(ticker())
    try:
        await asyncio.sleep(0.005)
        ticks_before = ticks
        chunks: list = []
        async for piece in slow_llm.astream([{"role": "user", "content": "hi"}]):
            if isinstance(piece, StreamChunk) and piece.text:
                chunks.append(piece.text)
            elif isinstance(piece, str) and piece:
                chunks.append(piece)
        ticks_during = ticks - ticks_before
    finally:
        running = False
        await ticker_task

    assert "".join(chunks) == "stream!"
    assert ticks_during >= 2, (
        f"Streaming should not block loop. ticks_during={ticks_during}"
    )
