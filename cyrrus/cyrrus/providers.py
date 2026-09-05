"""
Ready-made llm_call wrappers for common providers.
All receive a messages list and return a string.

Each wrapper is an async callable for Projector.process(), and also
exposes `.astream(messages)` for Projector.aprocess_stream() — an async
generator of StreamChunk values, so OpenAI/Groq/Anthropic/Ollama all
look the same to the pipeline.

Usage:
    from cyrrus.providers import ollama, openai, anthropic, groq

    bot = Projector(config, llm_call=ollama("llama3.2"))
    bot = Projector(config, llm_call=openai("gpt-4o-mini", api_key="sk-..."))
    bot = Projector(config, llm_call=anthropic("claude-haiku-4-5", api_key="sk-..."))
    bot = Projector(config, llm_call=groq("llama-3.1-8b-instant", api_key="..."))

These are thin wrappers. They don't install anything — use whatever SDK
you already have. Import errors tell you exactly what to install.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class StreamChunk:
    """One normalized piece of a streamed LLM response."""
    text: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[dict] = None


def _usage_from(obj: Any) -> Optional[dict]:
    usage = getattr(obj, "usage", None)
    if usage is None and isinstance(obj, dict):
        usage = obj.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if hasattr(usage, "dict"):
        return usage.dict()
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                "input_tokens", "output_tokens"):
        if hasattr(usage, key):
            out[key] = getattr(usage, key)
    return out or None


def normalize_openai_chunk(chunk: Any) -> StreamChunk:
    """
    OpenAI and Groq chat.completions streaming chunks.

    Role-only deltas (content is None) and empty choice lists are kept as
    StreamChunk(text=None, ...) so callers can ignore them.
    """
    if isinstance(chunk, dict):
        choices = chunk.get("choices") or []
        usage = _usage_from(chunk)
    else:
        choices = getattr(chunk, "choices", None) or []
        usage = _usage_from(chunk)

    if not choices:
        return StreamChunk(text=None, finish_reason=None, usage=usage)

    c0 = choices[0]
    if isinstance(c0, dict):
        delta = c0.get("delta") or {}
        finish = c0.get("finish_reason")
        if isinstance(delta, dict):
            text = delta.get("content")
        else:
            text = getattr(delta, "content", None)
    else:
        delta = getattr(c0, "delta", None)
        finish = getattr(c0, "finish_reason", None)
        if delta is None:
            text = None
        elif isinstance(delta, dict):
            text = delta.get("content")
        else:
            text = getattr(delta, "content", None)

    return StreamChunk(text=text, finish_reason=finish, usage=usage)


def normalize_groq_chunk(chunk: Any) -> StreamChunk:
    """Groq uses the OpenAI chat.completions streaming shape."""
    return normalize_openai_chunk(chunk)


def normalize_anthropic_text(text: Optional[str]) -> StreamChunk:
    """One piece from Anthropic's stream.text_stream."""
    return StreamChunk(text=text, finish_reason=None, usage=None)


def normalize_anthropic_final(message: Any) -> StreamChunk:
    """Final Anthropic message after the text stream (usage + stop reason)."""
    stop = getattr(message, "stop_reason", None)
    if stop is None and isinstance(message, dict):
        stop = message.get("stop_reason")
    return StreamChunk(text=None, finish_reason=stop, usage=_usage_from(message))


def normalize_ollama_chunk(chunk: Any) -> StreamChunk:
    """
    Ollama native chat stream: chunk['message']['content'] or
    chunk.message.content. `done` maps to finish_reason='stop'.
    """
    if isinstance(chunk, dict):
        msg = chunk.get("message") or {}
        if isinstance(msg, dict):
            text = msg.get("content")
        else:
            text = getattr(msg, "content", None)
        done = chunk.get("done")
        usage = _usage_from(chunk)
    else:
        msg = getattr(chunk, "message", None)
        if msg is None:
            text = None
        elif isinstance(msg, dict):
            text = msg.get("content")
        else:
            text = getattr(msg, "content", None)
        done = getattr(chunk, "done", False)
        usage = _usage_from(chunk)

    finish = "stop" if done else None
    return StreamChunk(text=text, finish_reason=finish, usage=usage)


def _split_system(messages: list) -> tuple:
    system = ""
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            filtered.append(m)
    return system, filtered


def ollama(model: str = "llama3.2", base_url: str = "http://localhost:11434") -> callable:
    """
    Local Ollama. Free, no API key needed.
    Setup: ollama serve && ollama pull llama3.2
    """
    import json
    import urllib.request

    async def _call(messages: list) -> str:
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer ollama",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]

    async def _astream(messages: list):
        try:
            from ollama import AsyncClient
        except ImportError:
            raise ImportError(
                "ollama package not found. Run: pip install ollama\n"
                "(needed for astream(); the non-streaming wrapper uses urllib.)"
            )
        client = AsyncClient(host=base_url)
        stream = await client.chat(model=model, messages=messages, stream=True)
        async for chunk in stream:
            yield normalize_ollama_chunk(chunk)

    _call.astream = _astream
    return _call


def openai(model: str = "gpt-4o-mini", api_key: str = None, base_url: str = None) -> callable:
    """
    OpenAI or any OpenAI-compatible API (Together, Fireworks, etc.).
    Requires: pip install openai
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ImportError(
            "openai package not found. Run: pip install openai\n"
            "Or use cyrrus.providers.ollama() for a free local option."
        )

    kwargs = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)

    async def _call(messages: list) -> str:
        r = await client.chat.completions.create(model=model, messages=messages)
        return r.choices[0].message.content

    async def _astream(messages: list):
        stream = await client.chat.completions.create(
            model=model, messages=messages, stream=True
        )
        async for chunk in stream:
            yield normalize_openai_chunk(chunk)

    _call.astream = _astream
    return _call


def anthropic(model: str = "claude-haiku-4-5", api_key: str = None, max_tokens: int = 1024) -> callable:
    """
    Anthropic Claude.
    Requires: pip install anthropic
    """
    try:
        import anthropic as _anthropic
    except ImportError:
        raise ImportError(
            "anthropic package not found. Run: pip install anthropic\n"
            "Or use cyrrus.providers.ollama() for a free local option."
        )

    client = _anthropic.AsyncAnthropic(api_key=api_key)

    async def _call(messages: list) -> str:
        system, filtered = _split_system(messages)

        kwargs = {"model": model, "max_tokens": max_tokens, "messages": filtered}
        if system:
            kwargs["system"] = system

        r = await client.messages.create(**kwargs)
        return r.content[0].text

    async def _astream(messages: list):
        system, filtered = _split_system(messages)
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": filtered}
        if system:
            kwargs["system"] = system

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield normalize_anthropic_text(text)
            final = await stream.get_final_message()
            yield normalize_anthropic_final(final)

    _call.astream = _astream
    return _call


def groq(model: str = "llama-3.1-8b-instant", api_key: str = None) -> callable:
    """
    Groq — fast inference, generous free tier. Good for testing.
    Requires: pip install groq
    """
    try:
        from groq import AsyncGroq
    except ImportError:
        raise ImportError(
            "groq package not found. Run: pip install groq\n"
            "Free tier at console.groq.com — no credit card needed."
        )

    client = AsyncGroq(api_key=api_key)

    async def _call(messages: list) -> str:
        r = await client.chat.completions.create(model=model, messages=messages)
        return r.choices[0].message.content

    async def _astream(messages: list):
        stream = await client.chat.completions.create(
            model=model, messages=messages, stream=True
        )
        async for chunk in stream:
            yield normalize_groq_chunk(chunk)

    _call.astream = _astream
    return _call
