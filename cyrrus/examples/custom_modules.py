"""
Runnable examples of custom cyrrus modules: tokenizer, renderer, fact
extractor, history summarizer, OpenAI-compatible provider, memory backend.

No network and no model: every LLM call goes to fake_llm, except the
openai_compatible example which talks to a throwaway stdlib HTTP server on
localhost.

Run:
    python cyrrus/examples/custom_modules.py
"""

import asyncio
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from cyrrus import MemoryBackend, MemoryVault, Projector
from cyrrus.providers import openai_compatible
from cyrrus.renderers import compact

TOKENIZER_CALLS = []
RENDERER_CALLS = []
EXTRACTOR_CALLS = []
SUMMARIZER_CALLS = []
PROVIDER_CALLS = []
BACKEND_CALLS = []

CONFIG = {"core_lamp": {"content": "You are a helpful assistant."}}


async def fake_llm(messages: list) -> str:
    return "fake reply"


class TokenizerObject:
    def encode(self, text: str):
        TOKENIZER_CALLS.append(("object", text))
        return [ord(c) for c in text]


def tokenizer_callable(text: str) -> int:
    TOKENIZER_CALLS.append(("callable", text))
    return max(1, len(text.split()))


def renderer(data: dict) -> str:
    RENDERER_CALLS.append(data)
    facts = "; ".join(s.content for s in data["facts"])
    return f"{data['base_system']} || facts: {facts}"


def sync_extractor(text: str) -> dict:
    EXTRACTOR_CALLS.append(("sync", text))
    if "my name is" in text.lower():
        return {"user_name": "Ada"}
    return {}


async def async_extractor(text: str) -> dict:
    await asyncio.sleep(0)
    EXTRACTOR_CALLS.append(("async", text))
    return {"user_city": "Lisbon"}


def sync_summarizer(old_messages: list) -> str:
    SUMMARIZER_CALLS.append(("sync", len(old_messages)))
    return "Earlier they talked about gardening."


async def async_summarizer(old_messages: list) -> str:
    await asyncio.sleep(0)
    SUMMARIZER_CALLS.append(("async", len(old_messages)))
    return "Earlier they talked about the beach."


class FakeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        PROVIDER_CALLS.append(self.path)
        body = b'{"choices":[{"message":{"content":"from local server"}}]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class DictBackend(MemoryBackend):
    def __init__(self) -> None:
        self.store: dict = {}
        self.calls: list = []

    async def init_db(self) -> None:
        pass

    async def upsert(
        self,
        session_id: str,
        keyword: str,
        value: str,
        tokens: int,
        max_facts_per_session: object,
        max_fact_value_length: int,
    ) -> None:
        BACKEND_CALLS.append(("upsert", session_id, keyword, value))
        self.store[(session_id, keyword)] = value

    async def retrieve_current(self, session_id: str, limit: int = 100) -> list:
        BACKEND_CALLS.append(("retrieve", session_id))
        return [
            (keyword, value, len(value.split()))
            for (sid, keyword), value in self.store.items()
            if sid == session_id
        ][:limit]

    async def touch(self, session_id: str, keywords: list) -> None:
        pass

    async def delete_session(self, session_id: str) -> int:
        BACKEND_CALLS.append(("delete_session", session_id))
        self.store = {k: v for k, v in self.store.items() if k[0] != session_id}
        return 0

    async def get_fact_history(self, session_id: str, keyword: str) -> list:
        return []

    async def close(self) -> None:
        pass


async def run_turns(bot, count: int, session_id: str = "s1") -> None:
    for i in range(count):
        await bot.process(f"turn {i}", session_id=session_id)
    await bot.flush()


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="cyrrus_custom_")

    # --- custom tokenizer: object with .encode ---
    tok_obj = TokenizerObject()
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory_db_path=f"{tmp}/tok_obj.db",
        tokenizer=tok_obj,
    )
    await run_turns(bot, 2)

    # --- custom tokenizer: callable str -> int ---
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory_db_path=f"{tmp}/tok_fn.db",
        tokenizer=tokenizer_callable,
    )
    await run_turns(bot, 2)
    assert TOKENIZER_CALLS, "tokenizer was never called"

    # --- custom renderer (built-in: cyrrus.renderers.compact) ---
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory_db_path=f"{tmp}/ren.db",
        renderer=renderer,
    )
    await bot.process("hello", session_id="s4")
    system = [m for m in bot.last_trace["messages"] if m["role"] == "system"][0]["content"]
    assert RENDERER_CALLS and "|| facts:" in system

    # built-in compact renderer
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory_db_path=f"{tmp}/ren_builtin.db",
        renderer=compact,
    )
    await bot.process("hello", session_id="s5")

    # --- custom fact extractor: sync, replace mode (default) ---
    backend_replace = DictBackend()
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory=MemoryVault(backend=backend_replace),
        memory_db_path=f"{tmp}/ext_replace.db",
        fact_extractor=sync_extractor,
    )
    await bot.process("my name is Ada", session_id="s6")
    await bot.flush()
    assert backend_replace.store.get(("s6", "user_name")) == "Ada"

    # --- custom fact extractor: async, merge mode ---
    backend_merge = DictBackend()
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory=MemoryVault(backend=backend_merge),
        memory_db_path=f"{tmp}/ext_merge.db",
        fact_extractor=async_extractor,
        extractor_mode="merge",
    )
    await bot.process("my name is Ada", session_id="s7")
    await bot.flush()
    assert EXTRACTOR_CALLS
    assert backend_merge.store.get(("s7", "user_city")) == "Lisbon"

    # --- custom history summarizer: sync and async ---
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        history_window=10,
        history_verbatim_turns=2,
        history_summarizer=sync_summarizer,
        memory_db_path=f"{tmp}/sum.db",
    )
    for i in range(6):
        await bot.process(f"turn {i} detail", session_id="s8")
    system_texts = [m["content"] for m in bot.last_trace["messages"] if m["role"] == "system"]
    assert SUMMARIZER_CALLS and all(n > 0 for _, n in SUMMARIZER_CALLS)
    assert any("gardening" in t for t in system_texts)

    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        history_window=10,
        history_verbatim_turns=2,
        history_summarizer=async_summarizer,
        memory_db_path=f"{tmp}/sum_async.db",
    )
    for i in range(6):
        await bot.process(f"turn {i} detail", session_id="s9")
    assert any(kind == "async" for kind, _ in SUMMARIZER_CALLS)

    # --- LLM provider via openai_compatible pointing at a local server ---
    server = HTTPServer(("127.0.0.1", 0), FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        llm = openai_compatible(base_url=f"http://127.0.0.1:{port}", model="local-model")
        reply = await llm([{"role": "user", "content": "hi"}])
        assert reply == "from local server"
        assert "/chat/completions" in PROVIDER_CALLS
    finally:
        server.shutdown()

    # --- custom memory backend ---
    backend = DictBackend()
    bot = Projector(
        CONFIG,
        llm_call=fake_llm,
        memory=MemoryVault(backend=backend),
        memory_db_path=f"{tmp}/mem.db",
    )
    await bot.process("my name is Ada", session_id="s10")
    await bot.flush()
    assert BACKEND_CALLS
    assert backend.store.get(("s10", "user_name")) == "Ada"

    print("all custom module examples ran and were called")


if __name__ == "__main__":
    asyncio.run(main())
