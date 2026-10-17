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

## Numbers

- **51.6% token reduction** on average across mixed conversations (real tiktoken counts)
- **0.018 MB** core install — zero required dependencies
- **121.9 MB / 241.7 MB RAM** for the optional embeddings block
- **500 concurrent users** with zero errors
- Surviving every adversarial test thrown at it

---

## Install

```bash
pip install cyrrus                  # core, zero dependencies
pip install cyrrus[embeddings]      # + semantic routing and memory
```

Python 3.9 to 3.13 are tested in CI.

The import is always:
```python
from cyrrus import Projector
```

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

Memory is per `session_id`. Facts never leak between users.

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

## Tracing

Every call stores a trace:

```python
await bot.process("write a script", session_id="u1")

trace = bot.last_trace
print(trace["routed_slide_ids"])        # which slides matched
print(trace["memory_slide_ids"])        # which facts were retrieved  
print(trace["dropped_slide_ids"])       # what didn't fit the budget
print(trace["messages"])                # exact messages sent to LLM
print(trace["stats"]["history_turns"])  # how many turns of history
```

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

---

## License

AGPLv3. If you run cyrrus as part of a network service, you must make your modifications available. See LICENSE.

---

cyrrus — formerly known as slid3s
