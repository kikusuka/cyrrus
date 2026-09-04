<div align="center">

# cyrrus

**Context routing for LLMs. The model only sees what matters right now.**

*Part of the [Breezy](#) ecosystem — formerly known as slid3s*

[![PyPI version](https://img.shields.io/pypi/v/cyrrus.svg)](https://pypi.org/project/cyrrus/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://pypi.org/project/cyrrus/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](https://pypi.org/project/cyrrus/)

```bash
pip install cyrrus
```

</div>

---

## The problem

Every time your app calls an LLM, it sends the same wall of system prompt. Every persona instruction, every tool definition, every rule — whether or not any of it matters to what the user just said.

Models get dumber when you do this. Not slower — *dumber*. Instructions contradict each other. Personas bleed across topics. The model starts ignoring things because there's too much to hold onto. This is a documented phenomenon called **"lost in the middle"** — and it gets worse, not better, as context windows grow. More room just means more junk gets stuffed in.

cyrrus fixes this by deciding what the model actually needs to see, turn by turn.

```python
from cyrrus import Projector
from cyrrus.providers import ollama

bot = Projector.minimal(llm_call=ollama("llama3.2"))
reply = bot.ask("hello")
```

Two lines. Zero dependencies. Works with any LLM.

---

## The idea

Think of your context as a deck of slides. Only the ones relevant to *this exact message* get shown to the model. Everything else stays off to the side — not deleted, not forgotten, just not in the way.

```
User: "write me a python function"
       └─→ code_lens slide activates
       └─→ casual_lens stays dormant

User: "hey how's it going"
       └─→ casual_lens activates
       └─→ code_lens starts to fade
```

### Ghost decay — the part nobody else has

Most context systems are binary: a topic is either in the prompt or it isn't. cyrrus does something closer to how human attention actually works. When a topic stops being actively discussed, it doesn't vanish — it **fades**.

```python
"code_lens": {
    "content": "Output only clean code blocks.",
    "triggers": ["code", "script", "python"],
    "active_turns": 6,      # stays warm through a real coding session
},
"casual_lens": {
    "content": "Keep it short and warm.",
    "triggers": ["hey", "hi", "hello"],
    "active_turns": 1,      # a greeting is over in one turn
},
```

Each slide can declare its own lifespan. A coding conversation naturally spans several turns — `code_lens` should still be warm on turn 4. A "hey" is done the moment it's answered. cyrrus lets every slide decide for itself how long it stays relevant, and fades it out gracefully instead of cutting it off.

This is a real trace from a live conversation:

```json
{
  "role": "system",
  "content": "You are a helpful assistant.\n\nOutput only clean code.\n\nAbout the user: building a Discord bot (fading — mentioned recently)"
}
```

The model still knows the user was building a Discord bot. It's just not front and center anymore.

---

## Why it's built this way

**Zero required dependencies.** The core install is 0.018 MB. No NumPy, no torch, nothing to fail to compile on a Raspberry Pi or in Termux on your phone. `cyrrus[embeddings]` is there when you want semantic routing, and it's entirely optional.

**Messages format, not string prompts.** cyrrus builds a real `[{"role": "system", ...}, {"role": "user", ...}]` array — the format every LLM API actually expects — with conversation history included, not a flattened string with made-up tags.

**Per-session memory that doesn't leak.** Facts are extracted from conversation automatically (no LLM call needed, pure heuristics) and isolated by `session_id`. User A never sees User B's data.

**It fails safely.** If routing breaks, if memory breaks, if a tool call hangs — cyrrus falls back to a raw LLM call instead of crashing your bot. This is tested: 60+ tests including adversarial scenarios (500 concurrent users, database deletion mid-write, prompt injection attempts, rotating exception types) all pass clean.

---

## Quickstart

### Zero config
```python
from cyrrus import Projector
from cyrrus.providers import ollama

bot = Projector.minimal(llm_call=ollama("llama3.2"))
reply = bot.ask("hello")
```

### With routing
```python
config = {
    "core_lamp": {"content": "You are a helpful assistant."},
    "code_lens": {
        "content": "Output only clean code, no filler.",
        "triggers": ["code", "script", "python", "function"],
        "active_turns": 6,
    },
}

bot = Projector(config, llm_call=ollama("llama3.2"))
reply = await bot.process("write a sorting function", session_id=str(user_id))
```

Only `content` is required. `tokens` and `priority` fill in automatically.

### Any provider
```python
from cyrrus.providers import ollama, openai, anthropic, groq

bot = Projector(config, llm_call=ollama("llama3.2"))
bot = Projector(config, llm_call=openai("gpt-4o-mini", api_key="sk-..."))
bot = Projector(config, llm_call=anthropic("claude-haiku-4-5", api_key="sk-..."))
bot = Projector(config, llm_call=groq("llama-3.1-8b-instant", api_key="..."))
```

Or bring your own — anything async that takes a messages list and returns a string:
```python
async def my_llm(messages: list) -> str:
    response = await client.chat.completions.create(model="...", messages=messages)
    return response.choices[0].message.content
```

---

## What's actually happening under the hood

```
message
   │
   ▼
┌──────────┐   which slides does this match?
│  Router  │   (keyword — zero deps, or semantic with [embeddings])
└────┬─────┘
     ▼
┌──────────┐   what does cyrrus already know about this user
│  Memory  │   that's relevant to this specific message?
└────┬─────┘
     ▼
┌──────────┐   fit the relevant stuff into the token budget,
│ Knapsack │   highest value-density first
└────┬─────┘
     ▼
┌──────────┐   what's still active, what's fading,
│   Tray   │   what's dropped since last turn?
└────┬─────┘
     ▼
┌──────────┐   build the real messages array, run any tools,
│Projector │   call your LLM, extract new facts in the background
└────┬─────┘
     ▼
 response
```

---

## Memory that just works

No setup. The default extractor runs automatically and picks up common patterns:

```
"my name is Muratha"          →  user_name = Muratha
"I'm building a Discord bot"  →  user_project = Discord bot
"I prefer Ollama"             →  user_preference = Ollama
```

With `cyrrus[embeddings]` installed, retrieval understands meaning, not just keyword overlap — "what am I working on" correctly finds a fact stored as `user_project`. Without it, keyword matching still catches most direct questions, zero dependencies required.

---

## What cyrrus is not

- **Not an agent framework.** It controls input. It never touches output, never calls itself recursively, never acts on your behalf.
- **Not a vector database.** Memory is SQLite. Simple, portable, no infrastructure to stand up.
- **Not a LangChain replacement.** It's a layer, not a framework. Use it inside whatever you're already building.
- **Not magic.** Keyword routing misses paraphrased questions. That's real, and it's why `cyrrus[embeddings]` exists.

---

## `session_id` — read this before you deploy

Every user needs a **unique** `session_id`, or they'll share memory with each other.

```python
# Discord bot
reply = await bot.process(message.content, session_id=str(message.author.id))

# Web app
reply = await bot.process(user_input, session_id=request.session["user_id"])

# Single-user script — ask() handles this for you
reply = bot.ask("hello")
```

---

## Install

```bash
pip install cyrrus                # core — zero dependencies
pip install cyrrus[embeddings]    # + semantic routing and memory
```

```python
from cyrrus import Projector
```

---

## Tracing — see exactly what the model saw

```python
await bot.process("write a script", session_id="u1")

trace = bot.last_trace
trace["routed_slide_ids"]        # which slides matched this turn
trace["memory_slide_ids"]        # which stored facts got pulled in
trace["dropped_slide_ids"]       # what didn't fit the budget
trace["messages"]                # the exact array sent to the LLM
```

Nothing is hidden. If the model does something unexpected, you can see exactly what it was given.

---

## License

AGPLv3. If you run cyrrus as part of a network service, your modifications need to be made available too.

---

<div align="center">

**cyrrus** — formerly slid3s — is the first library in the [Breezy](#) ecosystem.

</div>
💬 **[Join the Discord](https://discord.gg/fnCk8AYwVY)** — real-time updates, talk to other devs building on cyrrus, or just hang out.
