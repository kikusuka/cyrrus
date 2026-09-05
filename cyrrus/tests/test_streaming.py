"""
Streaming: aprocess_stream yields tokens, then post-processes.

process() is unchanged. History/fact extraction only run when the stream
finishes normally. Cancellation still writes the partial to the trace log.
"""
import asyncio
import os
import tempfile

import pytest

from cyrrus import Projector, StreamChunk
from cyrrus.providers import (
    normalize_anthropic_final,
    normalize_anthropic_text,
    normalize_groq_chunk,
    normalize_ollama_chunk,
    normalize_openai_chunk,
)


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _streaming_llm(text: str = "hello world"):
    async def llm(messages):
        return text

    async def astream(messages):
        # Yield progressively so tests can observe more than one chunk.
        if not text:
            yield StreamChunk(text=None, finish_reason="stop", usage=None)
            return
        mid = max(1, len(text) // 2)
        yield StreamChunk(text=text[:mid], finish_reason=None, usage=None)
        yield StreamChunk(text=text[mid:], finish_reason=None, usage=None)
        yield StreamChunk(text=None, finish_reason="stop", usage={"total_tokens": 3})

    llm.astream = astream
    return llm


def _bot(llm=None, **kwargs):
    kwargs.setdefault("memory_db_path", _db())
    return Projector.minimal(llm_call=llm or _streaming_llm(), **kwargs)


# ─── pipeline ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_yields_chunks_progressively():
    gate = asyncio.Event()
    order = []

    async def llm(messages):
        return "ab"

    async def astream(messages):
        order.append("chunk1")
        yield StreamChunk(text="a")
        await gate.wait()
        order.append("chunk2")
        yield StreamChunk(text="b")

    llm.astream = astream
    bot = _bot(llm)

    chunks = []

    async def consume():
        async for part in bot.aprocess_stream("hi", session_id="prog"):
            chunks.append(part)
            if part == "a":
                assert "chunk2" not in order
                gate.set()

    await consume()
    assert chunks == ["a", "b"]
    assert order == ["chunk1", "chunk2"]


@pytest.mark.asyncio
async def test_streamed_text_matches_process_for_same_provider():
    llm = _streaming_llm("hello world")
    bot = _bot(llm)
    via_process = await bot.process("same prompt", session_id="p1")

    bot2 = _bot(llm)
    pieces = []
    async for part in bot2.aprocess_stream("same prompt", session_id="p2"):
        pieces.append(part)

    assert via_process == "hello world"
    assert "".join(pieces) == via_process


@pytest.mark.asyncio
async def test_cancel_mid_stream_does_not_write_history():
    extracted = []

    async def llm(messages):
        return "full-response"

    async def astream(messages):
        yield StreamChunk(text="hel")
        await asyncio.sleep(60)
        yield StreamChunk(text="lo")

    llm.astream = astream

    async def extractor(text):
        extracted.append(text)
        return {"user_name": "Nope"}

    bot = _bot(llm, fact_extractor=extractor)
    got_first = asyncio.Event()
    chunks = []

    async def consume():
        async for part in bot.aprocess_stream("my name is Sam", session_id="cancel-me"):
            chunks.append(part)
            got_first.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(got_first.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert chunks == ["hel"]
    assert list(bot._get_history("cancel-me")) == []
    assert extracted == []
    assert bot.last_trace.get("error") == "CancelledError"
    assert bot.last_trace.get("response") == "hel"
    assert bot.last_trace.get("stream_complete") is False
    assert len(bot.trace_log) >= 1
    assert bot.trace_log[-1].get("response") == "hel"


@pytest.mark.asyncio
async def test_complete_stream_writes_history_and_extracts():
    extracted = []

    async def extractor(text):
        extracted.append(text)
        return {}

    bot = _bot(_streaming_llm("done"), fact_extractor=extractor)
    async for _ in bot.aprocess_stream("hello there", session_id="ok"):
        pass

    hist = list(bot._get_history("ok"))
    assert hist == [
        {"role": "user", "content": "hello there"},
        {"role": "assistant", "content": "done"},
    ]
    assert extracted == ["hello there"]
    assert bot.last_trace.get("stream_complete") is True
    assert bot.last_trace.get("response") == "done"


# ─── provider chunk adapters ─────────────────────────────────────────────────

class _Delta:
    def __init__(self, content=None):
        self.content = content


class _Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _OpenAIChunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices if choices is not None else []
        self.usage = usage


def test_openai_adapter_skips_none_deltas_and_reads_content():
    role_only = _OpenAIChunk(choices=[_Choice(delta=_Delta(content=None), finish_reason=None)])
    sc = normalize_openai_chunk(role_only)
    assert sc.text is None
    assert sc.finish_reason is None

    content = _OpenAIChunk(choices=[_Choice(delta=_Delta(content="Hi"), finish_reason=None)])
    sc = normalize_openai_chunk(content)
    assert sc == StreamChunk(text="Hi", finish_reason=None, usage=None)

    done = _OpenAIChunk(choices=[_Choice(delta=_Delta(content=None), finish_reason="stop")])
    sc = normalize_openai_chunk(done)
    assert sc.text is None
    assert sc.finish_reason == "stop"


def test_groq_adapter_matches_openai_shape():
    chunk = _OpenAIChunk(choices=[_Choice(delta=_Delta(content="tok"), finish_reason=None)])
    assert normalize_groq_chunk(chunk) == normalize_openai_chunk(chunk)
    assert normalize_groq_chunk(chunk).text == "tok"

    empty = _OpenAIChunk(choices=[])
    sc = normalize_groq_chunk(empty)
    assert sc.text is None


def test_anthropic_adapter_text_stream_and_final_usage():
    sc = normalize_anthropic_text("Hello")
    assert sc == StreamChunk(text="Hello", finish_reason=None, usage=None)

    class _Usage:
        input_tokens = 10
        output_tokens = 4

    class _Final:
        stop_reason = "end_turn"
        usage = _Usage()

    final = normalize_anthropic_final(_Final())
    assert final.text is None
    assert final.finish_reason == "end_turn"
    assert final.usage["input_tokens"] == 10
    assert final.usage["output_tokens"] == 4


def test_ollama_adapter_dict_and_attr_shapes():
    sc = normalize_ollama_chunk({"message": {"content": "hey"}, "done": False})
    assert sc.text == "hey"
    assert sc.finish_reason is None

    sc = normalize_ollama_chunk({"message": {"content": ""}, "done": True})
    assert sc.finish_reason == "stop"

    class _Msg:
        content = "attr"

    class _Chunk:
        message = _Msg()
        done = False

    sc = normalize_ollama_chunk(_Chunk())
    assert sc.text == "attr"
