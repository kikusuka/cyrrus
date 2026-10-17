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

import asyncio
import json
import socket
import urllib.request
import urllib.error
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
    parts = []
    filtered = []
    for m in messages:
        if m["role"] == "system":
            parts.append(m["content"])
        else:
            filtered.append(m)
    return "\n\n".join(parts), filtered


def ollama(
    model: str = "llama3.2",
    base_url: str = "http://localhost:11434",
    timeout: Optional[float] = 120.0,
) -> callable:
    """
    Local Ollama. Free, no API key needed.

    Two paths, both non-blocking to the asyncio event loop:
      * If the `ollama` pip package is installed: use AsyncClient directly.
      * Otherwise: stdlib urllib.request over HTTP, wrapped in
        asyncio.to_thread so the blocking socket call does not freeze
        the event loop.

    Args:
        model: Ollama model tag (e.g. "llama3.2", "mistral").
        base_url: Ollama server HTTP endpoint.
        timeout: Per-request timeout in seconds. Applied to both the
                 AsyncClient path AND the urllib fallback path. Use
                 None for no timeout.
    """
    try:
        from ollama import AsyncClient as _OllamaAsyncClient
    except ImportError:
        _OllamaAsyncClient = None

    if _OllamaAsyncClient is not None:
        client_kwargs = {"host": base_url}
        if timeout is not None:
            try:
                import httpx
                client_kwargs["client"] = httpx.AsyncClient(timeout=timeout)
            except Exception:
                pass
        client = _OllamaAsyncClient(**client_kwargs)

        async def _call(messages: list) -> str:
            response = await client.chat(model=model, messages=messages, stream=False)
            return response["message"]["content"]

        async def _astream(messages: list):
            stream = await client.chat(model=model, messages=messages, stream=True)
            async for chunk in stream:
                yield normalize_ollama_chunk(chunk)

        _call.astream = _astream
        return _call

    # ---------- Stdlib urllib fallback (blocking IO, wrapped in to_thread) ----------
    def _ollama_http_blocking(
        messages: list, *, stream: bool,
    ) -> Any:
        """Blocking HTTP POST to Ollama /api/chat. Runs in a thread pool."""
        payload = {"model": model, "messages": messages, "stream": stream}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        sock_timeout = socket._GLOBAL_DEFAULT_TIMEOUT if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=sock_timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"Ollama HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"
            ) from e
        if stream:
            # Stream: return list of NDJSON lines parsed into dicts
            lines = body.decode("utf-8", errors="replace").splitlines()
            return [json.loads(l) for l in lines if l.strip()]
        obj = json.loads(body.decode("utf-8", errors="replace"))
        return obj

    async def _call_fallback(messages: list) -> str:
        obj = await asyncio.to_thread(_ollama_http_blocking, messages, stream=False)
        if isinstance(obj, dict) and "message" in obj and "content" in obj["message"]:
            return obj["message"]["content"]
        raise RuntimeError(f"Unexpected Ollama response: {obj!r}")

    async def _astream_fallback(messages: list):
        chunks = await asyncio.to_thread(_ollama_http_blocking, messages, stream=True)
        for raw in chunks:
            yield normalize_ollama_chunk(raw)

    _call_fallback.astream = _astream_fallback
    return _call_fallback


def openai_compatible(
    base_url: str,
    model: str,
    api_key: Optional[str] = None,
    timeout: float = 120.0,
) -> callable:
    """
    OpenAI-compatible chat completions over stdlib urllib (Together, Fireworks,
    local vLLM, etc.). No extra dependencies.

    Two paths:
      * Normal call: POST {base_url}/chat/completions with stream:false,
        returns choices[0].message.content.
      * Streaming: same endpoint with stream:true; parses server-sent events
        ("data: {...}" lines, ending with "data: [DONE]") and yields
        StreamChunk values for each non-empty choices[0].delta.content.

    The returned callable exposes `.astream(messages)` for
    Projector.aprocess_stream(), same shape as ollama().

    Args:
        base_url: Server root, e.g. "http://localhost:8000". If it already
                  ends with "/chat/completions" it is used as-is. Trailing
                  slashes are stripped.
        model: Model name sent in the request body.
        api_key: When given, an "Authorization: Bearer <api_key>" header is
                 sent; otherwise no Authorization header is added.
        timeout: Per-request timeout in seconds. None disables it.
    """
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = endpoint + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _openai_http_blocking(
        messages: list, *, stream: bool,
    ) -> Any:
        """Blocking HTTP POST to OpenAI-compatible /chat/completions. Runs in a thread pool."""
        payload = {"model": model, "messages": messages, "stream": stream}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers=headers,
            method="POST",
        )
        sock_timeout = socket._GLOBAL_DEFAULT_TIMEOUT if timeout is None else timeout
        try:
            with urllib.request.urlopen(req, timeout=sock_timeout) as resp:
                body = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            raise RuntimeError(
                f"OpenAI-compatible API HTTP {e.code}: "
                f"{body.decode('utf-8', errors='replace')}"
            ) from e
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError(
                f"OpenAI-compatible API request failed: {e}"
            ) from e

        text = body.decode("utf-8", errors="replace")
        if stream:
            chunks = []
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                payload_str = line[len("data: "):]
                if payload_str.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(payload_str)
                except json.JSONDecodeError as je:
                    raise RuntimeError(
                        f"OpenAI-compatible API returned malformed SSE JSON (HTTP {status}): {payload_str!r}"
                    ) from je
                chunk = normalize_openai_chunk(obj)
                if chunk.text:
                    chunks.append(chunk)
            return chunks

        try:
            obj = json.loads(text)
        except json.JSONDecodeError as je:
            raise RuntimeError(
                f"OpenAI-compatible API returned malformed JSON (HTTP {status}): {text!r}"
            ) from je
        try:
            return obj["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"OpenAI-compatible API returned unexpected response (HTTP {status}): {obj!r}"
            ) from exc

    async def _call(messages: list) -> str:
        return await asyncio.to_thread(_openai_http_blocking, messages, stream=False)

    async def _astream(messages: list):
        chunks = await asyncio.to_thread(_openai_http_blocking, messages, stream=True)
        for chunk in chunks:
            yield chunk

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
