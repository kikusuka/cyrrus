"""
Ready-made llm_call wrappers for common providers.
All receive a messages list and return a string.

Usage:
    from cyrrus.providers import ollama, openai, anthropic, groq

    bot = Projector(config, llm_call=ollama("llama3.2"))
    bot = Projector(config, llm_call=openai("gpt-4o-mini", api_key="sk-..."))
    bot = Projector(config, llm_call=anthropic("claude-haiku-4-5", api_key="sk-..."))
    bot = Projector(config, llm_call=groq("llama-3.1-8b-instant", api_key="..."))

These are thin wrappers. They don't install anything — use whatever SDK
you already have. Import errors tell you exactly what to install.
"""


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

    return _call


def anthropic(model: str = "claude-haiku-4-5", api_key: str = None) -> callable:
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
        system = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        kwargs = {"model": model, "max_tokens": 1024, "messages": filtered}
        if system:
            kwargs["system"] = system

        r = await client.messages.create(**kwargs)
        return r.content[0].text

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

    return _call
