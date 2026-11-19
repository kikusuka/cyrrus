# cyrrus

**Context routing for LLM calls.**

Instead of sending a full static system prompt every time, cyrrus decides what context is relevant *right now* and sends only that.

```python
from cyrrus import Projector
from cyrrus.providers import ollama

bot = Projector.minimal(llm_call=ollama("llama3.2"))
reply = bot.ask("hello")
```

That's it. No config required to start.

## Using Cyrrus without async

If your script isn't running inside an async event loop, use the synchronous
wrapper. It runs on a private background event loop thread (created lazily,
reused across calls), so repeated calls share memory:

```python
from cyrrus import Projector

bot = Projector({"core_lamp": {"content": "You are helpful."}},
                llm_call=my_llm)
reply = bot.process_sync("hello", session_id="user_1")
bot.flush_sync()          # ensure background fact extraction is done
bot.close_sync()          # stop the background thread
```

Don't call `process_sync()` from inside FastAPI, Discord.py, or any async
framework — use `await process()` there instead. Calling it from a running
loop raises `RuntimeError`.

For simple single-user scripts, `bot.ask("hello")` also works (it runs
`asyncio.run()` under the hood).

In short scripts using the async API, call `await projector.flush()` (or use
`async with Projector(...)`) before exiting, or pass `wait_for_extraction=True`
to `process()` so each turn's facts are stored before the call returns.

---

## What it does

Every time a user sends a message, cyrrus:

1. **Routes** — matches the message against your slides to find what's relevant
2. **Remembers** — pulls stored facts about this user that relate to this message
3. **Packs** — fits the relevant context into your token budget, highest priority first
4. **Sends** — builds a proper messages array and calls your LLM
5. **Learns** — extracts new facts from the conversation and stores them for later

The LLM receives clean, relevant context. Not a wall of everything you've ever defined.

---

## What's measured

- **Zero required dependencies.** The core is standard-library only. Extras (`cyrrus[embeddings]`, `cyrrus[facts-onnx]`, `cyrrus[facts-torch]`) are optional.
- **Fewer tokens at the same recall:** on the 20-query holdout set, injected tokens fell from **359** in published `0.3.0b6` to **192** in this build (**46.5% fewer**), while mean injection recall stayed at **0.830** for both. The holdout set was written by the project's authors and was used while tuning, so it is a regression check, not independent evidence.
- **Retrieval quality:** on the holdout scenarios mean injection recall is **0.830**, identical to published `0.3.0b6`. On the main benchmark, mean recall is **0.900** across 10 scenarios, with **1** stale-leak total and a **0.000** mean distractor rate.
- **Latency:** with 50,000 facts in one session, a warm query measured **201 ms median / 485 ms p95**; the first query after a restart builds the index in **1.89 s**. At 1,000 facts: 4.1 ms median; at 5,000: 13.3 ms median. Published `0.3.0b6` measured 136 ms median at 50,000 in the same harness; repeat runs varied 109-201 ms across both versions, so treat them as comparable, not as a speedup.
- **Concurrency:** `tests/test_gateway.py` drives 200 concurrent requests; a separate run of the real `cyrrus serve` command served **50 of 50** concurrent requests with `requests=50, injected=50, fail_open=0`.
- **Compatibility:** CI runs Python 3.9-3.13 on Ubuntu 24.04. The built 0.3.0 wheel was also smoke-tested on Windows Python 3.9 and 3.13 and in `python:3.11-slim`.

These numbers come from `devtools/bench` in the source repository (not included in the PyPI package). It measures which facts get injected, **not answer quality**, and is written by the same team as cyrrus, so treat comparisons with that bias in mind.

## Known limitations

- **Paraphrases:** default retrieval is lexical (BM25). "Where do I live?" will not find "I moved to Porto" unless words overlap. The optional embedding retriever helps but is experimental and is not included in the numbers above.
- **Corrections under a different key:** "I no longer like pizza" does not retire an older fact stored under another key.
- **Topic switches:** old-topic facts can come back when words overlap. There is no topic expiry yet.
- **Precision:** with many look-alike facts, cyrrus finds the right one but also injects some similar noise.
- **First request after a restart** builds the search index for that session: 1.9 s at 50,000 facts on the test desktop, and longer for bigger sessions.
- **Gateway token strength:** `gateway.api_key_env` only checks that the incoming bearer token matches; it does **not** enforce a minimum length, and the gateway speaks plain HTTP. Use a long random token, for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`, and terminate TLS in a reverse proxy for anything non-local.
- **Windows shutdown:** closing the console window or killing the process does not drain pending turns; use Ctrl+C.
- **Not yet tested:** macOS, and Windows under file-replacement load.
- **Generic questions such as 'tell me about myself' inject nothing**, because no stored fact matches the words.
- **Selective injection can drop a relevant fact that scores below half of the best one.** Inspect `/cyrrus/last` to see what was dropped, or lower `memory.min_relative_score`.

---

## Install

Pick one of three routes.

**1. One-line installer** (uses `uv`, no admin rights, no Python knowledge):

```powershell
irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
```

```sh
curl -fsSL https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh
```

Pin an exact version with `-Version 0.3.0` (PowerShell) or `sh -s -- 0.3.0`. Open a new terminal afterwards and run `cyrrus setup`.

**2. pip** (existing Python 3.9-3.13):

```bash
python -m pip install cyrrus                 # core, zero dependencies
python -m pip install "cyrrus[embeddings]"   # + optional semantic retrieval
python -m cyrrus --version
```

**3. Standalone binary** (no Python): download the archive for your OS and CPU from the [latest release](https://github.com/kikusuka/cyrrus/releases/latest). The stable asset names are `cyrrus-windows-x64.zip`, `cyrrus-windows-arm64.zip`, `cyrrus-macos-arm64.tar.gz`, `cyrrus-macos-x64.tar.gz`, `cyrrus-linux-x64.tar.gz` and `cyrrus-linux-arm64.tar.gz`.

Docker: `ghcr.io/kikusuka/cyrrus:0.3.0` (see `docs/INSTALL.md`).

The import is always:

```python
from cyrrus import Projector
```

`docs/INSTALL.md` has checksums, version pinning, Docker, Termux/32-bit Raspberry Pi, Gatekeeper/SmartScreen and uninstall notes. Commands there were either run locally or marked **NOT RUN**.

---

## Three ways to use it

### Zero config

```python
from cyrrus import Projector
from cyrrus.providers import ollama

bot = Projector.minimal(llm_call=ollama("llama3.2"))
reply = bot.ask("write me a python function")
```

### With context routing

```python
config = {
    "core_lamp": {
        "content": "You are a helpful assistant.",
    },
    "code_lens": {
        "content": "Output only clean code blocks, no filler.",
        "triggers": ["code", "script", "python", "function", "bug"],
    },
    "casual_lens": {
        "content": "Keep it short and natural.",
        "triggers": ["hey", "hi", "hello"],
    },
}

bot = Projector(config, llm_call=ollama("llama3.2"))
reply = await bot.process("write a sorting function", session_id=str(user_id))
```

`tokens` and `priority` are optional — cyrrus fills them in automatically.

### Individual components

```python
from cyrrus import MemoryVault, IntentRouter, SlideTray

# Use any component standalone
memory = MemoryVault()
facts = await memory.retrieve("user_123", "what is my name", limit=3)
```

Projector also works as an async context manager — background fact extraction is awaited and cleaned up on exit:

```python
async with Projector(config, llm_call=ollama("llama3.2")) as bot:
    reply = await bot.process("hello", session_id=str(user_id))

# or manage the lifecycle yourself
bot = Projector(config, llm_call=ollama("llama3.2"))
reply = await bot.process("hello", session_id=str(user_id))
await bot.aclose()
```

---

## Providers

Ready-made wrappers for common APIs. Pass them directly as `llm_call`:

```python
from cyrrus.providers import ollama, openai, anthropic, groq

# Local Ollama — free, no API key
bot = Projector(config, llm_call=ollama("llama3.2"))

# OpenAI
bot = Projector(config, llm_call=openai("gpt-4o-mini", api_key="sk-..."))

# Anthropic
bot = Projector(config, llm_call=anthropic("claude-haiku-4-5", api_key="sk-..."))

# Groq — fast, generous free tier
bot = Projector(config, llm_call=groq("llama-3.1-8b-instant", api_key="..."))
```

Or bring your own — any async function that takes a messages list and returns a string:

```python
async def my_llm(messages: list) -> str:
    response = await client.chat.completions.create(
        model="my-model",
        messages=messages,
    )
    return response.choices[0].message.content

bot = Projector(config, llm_call=my_llm)
```

---

## Memory

cyrrus remembers things users tell it. No setup needed — the default extractor runs automatically:

```
User: "my name is Muratha"          → stored: user_name = Muratha
User: "I'm building cyrrus"         → stored: user_project = cyrrus
User: "I prefer Ollama"             → stored: user_preference = Ollama
```

On the next message, relevant facts are retrieved and injected into the system prompt automatically.

**With `cyrrus[embeddings]`:** retrieval uses semantic similarity, so "what am I working on" finds `user_project: cyrrus` even without shared keywords.

**Without:** keyword overlap matching. Fast, zero dependencies, catches most cases.

When an embedder is active, retrieval is **hybrid**: keyword/alias matches (BM25) come first in ranking order, then embedding-only matches with cosine score >= `embedding_min_score` are added, de-duplicated by fact id and capped at the limit. Keyword matches never need an embedding score. Facts failing both are reported as "below threshold" in the trace.

`embedding_min_score` defaults to 0.68, calibrated for BAAI/bge-small-en-v1.5 on a small measurement. Pass a lower value to admit more facts, or a higher one to be stricter:

```python
memory = MemoryVault(embedder=my_model, embedding_min_score=0.5)
```

Memory is per `session_id`. Facts never leak between users.

## Your data: forget and export

cyrrus lets you delete and export user data:

```python
# Delete one fact (all versions, including superseded)
await bot.forget_fact("user_123", "user_name")

# Delete all facts for a session; also clears in-memory tray and history
count = await bot.forget_session("user_123")

# Export all current facts as JSON-serializable dicts
facts = await bot.export_facts("user_123")
# [{'key': 'user_name', 'value': 'Alice', 'created': '...', 'invalid_at': None}, ...]

# Include superseded versions
facts = await bot.export_facts("user_123", include_superseded=True)
```

These work on `Projector` (delegating to `MemoryVault` and the backend) and on
`MemoryVault` directly. Custom backends inherit `NotImplementedError` defaults
unless they override the methods.

---

## Conversation history

cyrrus maintains a sliding window of conversation history per session. The LLM always sees recent context, so follow-up questions work:

```
User: "what's the capital of France?"
Bot:  "Paris."
User: "what's the population there?"   ← LLM knows "there" means Paris
Bot:  "Around 2.1 million in the city proper."
```

---

## What cyrrus is not

- **Not an agent framework.** It controls input, never output.
- **Not a vector database.** Memory is SQLite with semantic retrieval optional.
- **Not a replacement for LangChain.** It's a layer, not a framework.
- **Not magic.** Keyword routing misses natural phrasing. Install `cyrrus[embeddings]` if you need paraphrase matching.

---

## session_id

This is important. Every user needs a unique `session_id`:

```python
# Discord bot
reply = await bot.process(message.content, session_id=str(message.author.id))

# Web app
reply = await bot.process(user_input, session_id=request.session["user_id"])

# Single-user script — use ask() and don't worry about it
reply = bot.ask("hello")
```

Without a unique session_id, users share memory. That's a bug, not a feature.

---

## Chat adapter

`cyrrus.adapters.make_chat()` builds a single `chat(session_id, user_text)`
coroutine you can drop into a Discord/Slack/Telegram bot in two lines.

**15-line Discord bot example:**

```python
import discord, os, asyncio
from cyrrus import Projector
from cyrrus.adapters import make_chat
from cyrrus.providers import ollama  # or openai / anthropic / groq

SLIDES = {"core_lamp": {"content": "You are a friendly assistant."}}
client = discord.Client(intents=discord.Intents.default())
bot = Projector(SLIDES, llm_call=ollama("llama3.2"))
chat = make_chat(bot)

@client.event
async def on_message(m):
    if m.author == client.user or not m.content.startswith("!"):
        return
    reply = await chat(str(m.author.id), m.content[1:].strip())
    await m.channel.send(reply[:2000])

asyncio.run(client.start(os.environ["DISCORD_TOKEN"]))
```

---

## Seeing what cyrrus did

Every call stores a trace on the projector:

```python
await bot.process("write a script", session_id="u1")

trace = bot.last_trace
print(trace["routed_slide_ids"])        # which slides matched
print(trace["memory_slide_ids"])        # which facts were injected
print(trace["dropped_slide_ids"])       # what did not fit, with reasons
print(trace["candidates"])              # fact and slide candidates with include/drop reasons
print(trace["messages"])                # exact messages sent to the LLM
print(trace["stats"]["history_turns"])  # how many turns of history
```

`last_trace` is local to your process and can contain the system message and fact
values; fact values appear only when `memory.trace_values` is true (default
false).

For the gateway, `GET /cyrrus/last` returns the last 50 decisions: session,
routed and ghost slides, fact **keys** and scores, candidates with include/drop
reasons, retrieval stats and timing. It does **not** include prompt text or fact
values by default. `cyrrus serve --log-prompts` adds the rendered context for
debugging. Verified on the built wheel: after 50 concurrent requests,
`/cyrrus/last` contained neither the request text nor a seeded fact value.

## Plugins

Three slots can be replaced: `retriever`, `packer` and `backend`. Built-ins are
`bm25` (the default), `hybrid`, `token_knapsack` and `sqlite`. Select a plugin in
`cyrrus.config.json`:

```json
{
  "plugins": {
    "retriever": "hybrid",
    "packer": null,
    "backend": null
  }
}
```

or pass it to the constructor with `Projector(..., plugins={"packer": "my_packer"})`.
Third-party plugins are discovered through the `cyrrus.plugins` entry-point
group; an entry point may be an object, a class or a factory accepting a config
mapping. Selection is lazy: with the default config no entry points are scanned
and no third-party code is imported. An unknown selected name raises
`LookupError` listing the available names. Plugin code runs in your process when
selected, so review a plugin before installing it.

## Experimental embedding retriever

Default retrieval is keyword BM25 and needs no extras. To add semantic matches,
install the optional packages and give the memory vault an embedder or model:

```bash
python -m pip install "cyrrus[embeddings]"
```

```python
from cyrrus import MemoryVault, Projector

memory = MemoryVault(embedding_model="BAAI/bge-small-en-v1.5")
bot = Projector(config, llm_call=my_llm, memory=memory)
```

Keyword matches stay first; embedding-only facts are added when cosine
similarity is at least `embedding_min_score`, de-duplicated and capped at the
fact limit. If the model cannot load or an embedding call fails, retrieval logs
one warning and falls back to keywords. **The text of your stored facts is sent
to the embeddings endpoint you configure. Use a local endpoint such as Ollama
for private data.** Verified with a deterministic fake
embedder: a query sharing no words with the stored fact ("which municipality am
I based in") injected "I live in Porto" through the embedding path only.

This path is opt-in, experimental, not used for the published quality/latency
numbers, and the recommended model is English. The first use downloads model
weights. `memory.embedding_min_score` is 0.7 in the shipped config defaults;
direct `MemoryVault`/`Projector` construction defaults to 0.68.

---

## Writing your own modules

Every internal component of `Projector` is swappable via constructor arguments.

### Custom tokenizer

Used for token budgeting. Pass an object with `.encode(text)`, or any callable `str -> int`:

```python
class WordTokenizer:
    def encode(self, text: str):
        return text.split()

bot = Projector(config, llm_call=my_llm, tokenizer=WordTokenizer())

# or a plain callable
def count(text: str) -> int:
    return max(1, len(text.split()))

bot = Projector(config, llm_call=my_llm, tokenizer=count)
```

### Custom renderer

The renderer receives `{"slides", "ghosts", "facts", "base_system"}` and returns the system message string:

```python
from cyrrus.renderers import compact

# built-in compact renderer
bot = Projector(config, llm_call=my_llm, renderer=compact)

# custom renderer
def my_renderer(data: dict) -> str:
    facts = "; ".join(s.content for s in data["facts"])
    return f"{data['base_system']} | {facts}"

bot = Projector(config, llm_call=my_llm, renderer=my_renderer)
```

### Custom fact extractor

Sync or async; returns `{key: value}` or a list of `(key, value)` tuples. `extractor_mode="replace"` (default) hides the built-in facts; `"merge"` lets custom facts win on key conflicts:

```python
def my_extractor(text: str) -> dict:
    return {"user_name": "Ada"} if "my name is" in text else {}

bot = Projector(config, llm_call=my_llm, fact_extractor=my_extractor)

async def my_extractor(text: str) -> dict:
    return {"user_city": "Lisbon"}

bot = Projector(config, llm_call=my_llm, fact_extractor=my_extractor, extractor_mode="merge")
```

### Custom history summarizer

Sync or async; receives older history messages and returns a summary string that replaces them in the prompt:

```python
def summarize(old_messages: list) -> str:
    return "Earlier turns covered gardening."

bot = Projector(
    config,
    llm_call=my_llm,
    history_summarizer=summarize,
    history_verbatim_turns=2,
)

# async summarizers work the same way
async def summarize(old_messages: list) -> str:
    return "summary"
```

### LLM provider via openai_compatible

Point at a local server (vLLM, Ollama, anything OpenAI-compatible) using stdlib only:

```python
from cyrrus.providers import openai_compatible

llm = openai_compatible(base_url="http://localhost:8000/v1", model="local-model")
reply = await llm([{"role": "user", "content": "hi"}])
bot = Projector(config, llm_call=llm)
```

### Custom memory backend

Subclass `MemoryBackend` and pass it to `MemoryVault`:

```python
from cyrrus import MemoryBackend, MemoryVault

class MyBackend(MemoryBackend):
    async def init_db(self): ...
    async def upsert(self, session_id, keyword, value, tokens, max_facts_per_session, max_fact_value_length): ...
    async def retrieve_current(self, session_id, limit=100): ...
    async def touch(self, session_id, keywords): ...
    async def delete_session(self, session_id): ...
    async def get_fact_history(self, session_id, keyword): ...
    async def close(self): ...

bot = Projector(config, llm_call=my_llm, memory=MemoryVault(backend=MyBackend()))
```

Full runnable examples: `cyrrus/examples/custom_modules.py`.

## Guided setup

Run `cyrrus setup` to configure a provider, storage, renderer, starter slides,
and (optionally) the local gateway. On a first interactive run, plain `cyrrus`
plays the intro and opens setup; afterwards it opens the home menu. Keep
`cyrrus home` as the explicit alias, or replay onboarding with `cyrrus --tour`.
When stdout is not a terminal (or in CI/protocol use), plain `cyrrus` prints
help instead of prompting.

Menus accept arrow keys and a numbered fallback. For automation:

```
cyrrus setup --non-interactive --dry-run
cyrrus setup --non-interactive --service ollama --model qwen2.5-coder:0.5b \
    --gateway-mode inject --yes
```

API keys are never accepted as command-line arguments, because command lines
leak into shell history and process lists. Use `--api-key-env NAME` to store
only the variable name in the config, or pipe a value to `--api-key-stdin`; the
value is written only to `.env` (which setup adds to `.gitignore`). Passing
`--api-key VALUE` exits with an explanation of those two safe options.

## Gateway mode

```
+-------------+    OpenAI-compatible    +---------------------+    +----------+
| editor /    | ----------------------> | cyrrus serve        | -> | provider |
| OpenAI SDK  |  http://127.0.0.1:8787  | context + memory    |    | (model)  |
+-------------+ <---------------------- +---------------------+ <- +----------+
```

Start it with `cyrrus serve`, then point any OpenAI-compatible client at
`http://127.0.0.1:8787/v1`. `cyrrus setup show zed|python|curl` prints
copy-ready snippets. The gateway is a proxy, not a chat UI: it adds Cyrrus
context and forwards the request and response unchanged.

Zed (`settings.json`, extend with your own model names):

```json
{
  "language_models": {
    "openai_compatible": {
      "cyrrus": {
        "api_url": "http://127.0.0.1:8787/v1",
        "available_models": [
          { "name": "cyrrus", "max_tokens": 8192 }
        ]
      }
    }
  }
}
```

OpenAI Python SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key="unused")
reply = client.chat.completions.create(
    model="cyrrus",  # resolves to the configured provider model
    messages=[{"role": "user", "content": "What should I work on next?"}],
    extra_headers={"X-Cyrrus-Session": "work"},
)
print(reply.choices[0].message.content)
```

Modes:

* `inject` (default) keeps the client's history and prepends Cyrrus context.
* `manage` also compacts older history to the token budget, keeping system
  messages and the newest exchange; it may use the configured summarizer hook.
  Requests carrying `tools` or tool messages are always handled as `inject`.
* `gateway.force_model` overrides the client's model; an empty model or
  `cyrrus` uses the configured provider model.

Context construction fails open by default: if routing or memory fails, the
original request is forwarded untouched (`gateway.fail_open: false` makes it an
error instead). Override the session with `X-Cyrrus-Session: <id>`, or set
`X-Cyrrus-Skip: 1` to bypass Cyrrus context for one request.

Limits: the gateway speaks the OpenAI chat-completions API only; the native
Anthropic API is not supported. Editors may make extra utility calls (for
example thread titles) that also pass through the gateway, and some editor
features cannot be redirected to it. Requests are capped at 10 MB, and binding
to a non-loopback host requires `gateway.api_key_env`.

---

## License

AGPLv3. If you run cyrrus as part of a network service, you must make your modifications available. See LICENSE.

---

cyrrus — formerly known as slid3s
