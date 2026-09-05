# The cyrrus Guide

*Everything you need to actually use cyrrus well — not just the API, but why it works the way it does and how to get the most out of it.*

---

## Table of contents

1. [The five-minute start](#the-five-minute-start)
2. [CLI Quickstart](#cli-quickstart)
3. [Streaming](#streaming)
4. [Understanding slides](#understanding-slides)
5. [Writing good triggers](#writing-good-triggers)
6. [The ghost decay model, explained properly](#the-ghost-decay-model-explained-properly)
7. [Memory — how it learns about your users](#memory--how-it-learns-about-your-users)
8. [Choosing a Fact Extraction Tier](#choosing-a-fact-extraction-tier)
9. [Tools — giving your bot capabilities](#tools--giving-your-bot-capabilities)
10. [Token budgets and priority](#token-budgets-and-priority)
11. [session_id — the thing you must not skip](#session_id--the-thing-you-must-not-skip)
12. [Choosing a provider](#choosing-a-provider)
13. [Debugging with traces](#debugging-with-traces)
14. [When to use semantic routing](#when-to-use-semantic-routing)
15. [Common mistakes](#common-mistakes)
16. [Production checklist](#production-checklist)

---

## The five-minute start

Install it:
```bash
pip install cyrrus
```

If you have Ollama running locally:
```bash
ollama serve
ollama pull llama3.2
```

Then:
```python
from cyrrus import Projector
from cyrrus.providers import ollama

bot = Projector.minimal(llm_call=ollama("llama3.2"))
reply = bot.ask("hello, who are you?")
print(reply)
```

That's a working bot in five lines. No config file. No JSON. `Projector.minimal()` builds a bare-bones config with just a base persona under the hood.

If you want to change the personality:
```python
bot = Projector.minimal(
    llm_call=ollama("llama3.2"),
    persona="You are a sarcastic pirate who reluctantly helps with coding questions."
)
```

That's genuinely as far as you need to go for a lot of use cases. Everything past this point is for when you want more control.

---

## CLI Quickstart

If you'd rather not hand-write config, use the built-in wizard:

```bash
cyrrus init
```

For scripted setup:

```bash
cyrrus init --template coding --tone professional --yes
```

On Windows, if `cyrrus` isn't recognized because the Scripts folder is not on `PATH`, run:

```bash
python -m cyrrus.cli init
```

---

## Streaming

Use `process()` when you want a single final string. Use `aprocess_stream()` when you want to render output token-by-token in a live UI, terminal, or chat bridge.

```python
async for chunk in bot.aprocess_stream("Draft release notes", session_id="u1"):
    print(chunk, end="", flush=True)
```

Behavior differences vs `process()`:

- `process()` returns one completed response and always records that completed turn.
- `aprocess_stream()` yields pieces as they arrive, then finalizes post-processing when streaming completes.
- If a stream is cancelled or errors mid-flight, the partial assistant response is **not** saved to conversation history, and fact extraction for that turn is skipped.

---

## Understanding slides

A **slide** is a named block of context. Think of it as a card that says "if this topic comes up, show the model this."

```python
config = {
    "core_lamp": {
        "content": "You are a customer support assistant for Acme Corp.",
    },
    "refund_policy": {
        "content": "Refunds are available within 30 days with a receipt. No refunds on final sale items.",
        "triggers": ["refund", "return", "money back"],
    },
    "shipping_info": {
        "content": "Standard shipping takes 5-7 business days. Express is 2-3 days.",
        "triggers": ["shipping", "delivery", "when will it arrive"],
    },
}
```

**`core_lamp` is special.** It's required, it's always included, and it's the highest priority by default (1000). Everything else is optional.

Every slide has exactly one required field: `content`. Everything else — `tokens`, `priority`, `active_turns`, `triggers` — has a sensible default if you leave it out.

```python
# This is a completely valid slide:
"weather": {"content": "Weather information is available.", "triggers": ["weather"]}
```

`tokens` auto-computes from word count. `priority` defaults to 500 (or 1000 for the lamp). You genuinely don't need to think about these until you're tuning things.

### Slide types

| type | what it does |
|---|---|
| `lamp` | the base persona, always active (used automatically for core_lamp) |
| `lens` | modifies behavior — tone, formatting, focus |
| `tool` | activates a tool call when triggered |
| `memory` | auto-generated, don't create these manually |
| `data` | generic context block (this is the default if you don't specify) |

Most slides you write will just be `lens` or `tool`. `data` is the fallback for anything else — a fact, a policy, a piece of reference material.

---

## Writing good triggers

Triggers are the words that make a slide fire. This is the single biggest lever you have over how well cyrrus behaves.

**Do this:**
```python
"triggers": ["code", "script", "python", "function", "bug", "error", "debug"]
```

Cast a wide net of the actual words people use. Include synonyms. Include the informal version ("bug") and the formal version ("error").

**Don't do this:**
```python
"triggers": ["code"]
```

One trigger word means you'll miss "can you help me script this" or "there's a bug in my function." Every trigger you don't think of is a message that silently gets no context.

### A trick that helps: think in verbs and nouns separately

For a weather slide, don't just write `["weather"]`. Think about how people actually ask:
```python
"triggers": ["weather", "rain", "forecast", "temperature", "umbrella", "sunny", "cold", "hot"]
```

People rarely say the word "weather" directly. They say "is it going to rain" or "should I bring an umbrella." Keyword matching is dumb by design — it only works with the exact words present. Compensate by thinking about the actual vocabulary of the topic, not just its name.

### Negation is handled for you

```python
"don't search for that" → search slide does NOT fire
"skip the code formatting" → code_lens does NOT fire
```

cyrrus looks a few words back from any trigger match for negation words (`don't`, `never`, `skip`, `without`, `not`). You don't need to build this yourself.

### When keywords aren't enough

If your users phrase things in ways that never share literal words with your triggers — "I need to automate this spreadsheet task" instead of "write me a script" — keyword matching will miss it every time. That's what `examples` and `cyrrus[embeddings]` are for. More on this in [When to use semantic routing](#when-to-use-semantic-routing).

---

## The ghost decay model, explained properly

This is the part of cyrrus that's genuinely different from everything else.

Most systems treat context as binary: a topic is either included or it isn't, decided fresh every single turn. This causes a specific, annoying failure: the model forgets what you were just talking about the instant you stop using the exact trigger word.

```
Turn 1 — "help me write a sorting function"     → code_lens: ACTIVE
Turn 2 — "make it handle duplicates too"        → code_lens: ACTIVE (still coding, but no "code" keyword this turn!)
Turn 3 — "nice, thanks"                         → code_lens: fading
Turn 4 — "what's your favorite color"           → code_lens: gone
```

Without ghost decay, turn 2 would silently lose the code formatting instruction the moment the user stopped literally saying "code." The tray keeps a slide **active** for a configurable number of turns after its last trigger — not just the turn it was triggered on.

### How TTL works

```python
"code_lens": {
    "content": "Output only clean code blocks.",
    "triggers": ["code", "script", "bug"],
    "active_turns": 6,   # stays active for 6 turns without re-triggering
}
```

Every turn the slide isn't re-triggered, its internal counter increments. Once the counter exceeds `active_turns`, it becomes a **ghost** — shown to the model with a fading note instead of dropped instantly:

```
"Output only clean code blocks. (fading — mentioned recently)"
```

The model still knows the topic was relevant recently. It's just told, honestly, that it's fading. If the topic comes back up (re-triggered), the counter resets to zero and it's fully active again — no lingering fade note.

### Choosing active_turns per slide

Think about how long a real conversation about that topic naturally lasts:

```python
"casual_lens":   {"active_turns": 1}   # a greeting is done in one exchange
"code_lens":     {"active_turns": 6}   # a debugging session spans several turns
"political_lens":{"active_turns": 4}   # a policy discussion has some legs
"weather_tool":  {"active_turns": 1}   # you asked, you got the answer, done
```

If you don't set `active_turns`, the slide falls back to the global `max_active_turns` (default: 2).

```python
bot = Projector(config, llm_call=my_llm, max_active_turns=2)  # the global default
```

### Ghost capacity

Only so many ghosts can exist at once (`max_ghost_slides`, default 5). This stops the system message from filling up with fading nostalgia about every topic ever mentioned. Oldest ghosts get dropped first once the cap is hit.

---

## Memory — how it learns about your users

cyrrus extracts facts from what users say and remembers them, automatically, with zero setup:

```
"my name is Jordan"           → user_name: Jordan
"I work at a startup"         → user_workplace: a startup
"I'm building a mobile app"   → user_project: a mobile app
"I prefer dark mode"          → user_preference: dark mode
```

No LLM call is made to do this. It's a set of careful regex heuristics, chosen because they're fast, free, and predictable. This means it won't catch every possible way someone might state a fact — but it also won't ever cost you an API call just to remember something.

### How retrieval works

When a user sends a message, cyrrus checks stored facts for relevance and injects the matching ones:

```
Stored: user_name = Jordan
User asks: "what's my name?"
→ system message includes: "About the user: Jordan"
```

**Without `cyrrus[embeddings]`:** retrieval is keyword overlap. "What's my name" shares the word "name" with the stored key `user_name`, so it matches. But "who am I talking to" would miss it entirely — no shared words.

**With `cyrrus[embeddings]`:** retrieval understands meaning. "What am I working on" correctly finds a fact stored as `user_project` even with zero word overlap, because the embedding model understands they're semantically related.

### Facts never leak between users

Memory is strictly isolated by `session_id`. This is tested — 500 concurrent sessions, zero cross-contamination, confirmed under adversarial load.

### Temporal Memory

Facts now version over time instead of overwriting old values. When a key changes, cyrrus marks the previous value as invalid and stores the new one as the current value.

If you need the timeline for one fact, use `get_fact_history(session_id, keyword)` on `MemoryVault` to retrieve all versions in chronological order (current + superseded).

### Bringing your own extractor

If the built-in heuristics don't fit your domain, replace it entirely:

```python
async def my_extractor(user_message: str) -> dict:
    facts = {}
    if "allerg" in user_message.lower():
        facts["dietary_restriction"] = user_message
    return facts

bot = Projector(config, llm_call=my_llm, fact_extractor=my_extractor)
```

Or disable extraction entirely:
```python
bot = Projector(config, llm_call=my_llm, fact_extractor=None)
```

### Deleting a user's data

```python
await bot.memory.delete_session("user_123")
```

Useful for GDPR-style deletion requests, or just letting a user reset their history.

---

## Choosing a Fact Extraction Tier

cyrrus supports three extraction tiers:

- **Regex (default):** zero dependencies, fastest startup, most predictable behavior. Best default when you want minimal footprint.
- **ONNX tier (`pip install cyrrus[facts-onnx]`):** improved recall for natural phrasing with a moderate dependency footprint. Good middle ground.
- **Torch tier (`pip install cyrrus[facts-torch]`):** highest extraction quality on varied language, but largest install/runtime footprint.

Rule of thumb: start with regex, move to ONNX when misses become visible in production phrasing, and use torch when extraction quality matters more than package size and startup cost.

---

## Tools — giving your bot capabilities

A tool slide activates a function call when triggered:

```python
config = {
    "core_lamp": {"content": "You are a helpful assistant."},
    "weather_tool": {
        "type": "tool",
        "content": "Weather lookup is active.",
        "handler": "get_weather",
        "triggers": ["weather", "forecast", "rain"],
        "tool_estimate_tokens": 60,   # how much budget to reserve for the result
    },
}

async def get_weather(user_message: str) -> str:
    # call a real weather API here
    return "72°F, sunny, light breeze"

bot = Projector(
    config,
    llm_call=my_llm,
    tool_executors={"get_weather": get_weather},
)
```

When the weather slide fires, cyrrus runs `get_weather()`, wraps the result in explicit safety framing (so the model treats it as data, not instructions), and appends it to the user message.

### Why tool_estimate_tokens matters

cyrrus reserves budget for tool output **before** running the tool — not after. If you don't set `tool_estimate_tokens`, it defaults to 150. If your tool tends to return more or less than that, tell it, or you'll either waste budget or risk the response getting truncated:

```python
"web_search": {"tool_estimate_tokens": 200}   # search results are verbose
"weather_tool": {"tool_estimate_tokens": 60}   # weather is compact
```

### Tool timeouts

Tools have a timeout so a hanging API call doesn't hang your whole bot. Default is 5 seconds; failed or timed-out tools return gracefully rather than crashing the request.

---

## Token budgets and priority

```python
bot = Projector(config, llm_call=my_llm, max_context_tokens=800)
```

This is the total budget for the system message (lamp + active slides + memory facts). It does **not** include the user's message or conversation history — those are added on top.

### How packing works

cyrrus sorts candidate slides by **priority ÷ tokens** — the highest "value per token" wins the budget first. A short, high-priority slide always beats a long, low-priority one for a spot in the prompt.

```python
"core_lamp":  priority=1000  →  always wins, always included
"code_lens":  priority=900   →  wins over lower-priority slides when budget is tight
"casual_lens":priority=700   →  loses out first if budget runs short
```

If you don't set priority, non-lamp slides default to 500. Set it higher for anything that must not get dropped, lower for anything that's nice-to-have.

### What happens when the budget runs out

Lower-priority slides get dropped entirely, cleanly, with no partial truncation. You can see exactly what got dropped via the trace (`trace["dropped_slide_ids"]`).

---

## session_id — the thing you must not skip

Every distinct user needs a **unique** `session_id`. This isn't optional polish — it's the boundary that keeps memory and conversation history from leaking between different people.

```python
# Discord — use the author's ID
reply = await bot.process(message.content, session_id=str(message.author.id))

# Web app — use the logged-in user's ID or session token
reply = await bot.process(user_input, session_id=request.session["user_id"])

# Telegram
reply = await bot.process(text, session_id=str(update.effective_user.id))
```

If you use `session_id="default"` for every user (easy to do by accident if you copy-paste an example), cyrrus will warn you loudly in the logs — but it will still technically run, and every user will share the same memory and history. This is a real, quiet, embarrassing bug waiting to happen. Don't skip it.

**For single-user local scripts**, `bot.ask()` handles this automatically and safely — you don't need to think about session_id at all in that case.

---

## Choosing a provider

```python
from cyrrus.providers import ollama, openai, anthropic, groq
```

| Provider | When to use it |
|---|---|
| `ollama("llama3.2")` | Local, free, private. Best for development and privacy-sensitive apps. |
| `groq("llama-3.1-8b-instant")` | Fast, generous free tier. Great for testing without local setup. |
| `openai("gpt-4o-mini")` | Reliable, well-documented, widely supported. |
| `anthropic("claude-haiku-4-5")` | Strong instruction-following, good for anything nuanced. |

All four just wrap the underlying SDK. If you need a provider not listed, write your own — it just needs to be an async function that takes a messages list and returns a string:

```python
async def my_llm(messages: list) -> str:
    response = await some_client.chat(messages=messages)
    return response.text

bot = Projector(config, llm_call=my_llm)
```

---

## Debugging with traces

Every call to `process()` records a full trace of what happened:

```python
await bot.process("write a python script", session_id="u1")

trace = bot.last_trace
print(trace["routed_slide_ids"])   # ['code_lens'] — what matched
print(trace["memory_slide_ids"])   # [] — no relevant facts this turn
print(trace["dropped_slide_ids"])  # [] — nothing got cut for budget
print(trace["messages"])           # the exact array sent to the LLM
print(trace["stats"])              # word counts, history turns, active/ghost counts
```

If your bot ever behaves strangely — wrong tone, missing context, unexpected memory — the trace tells you exactly what cyrrus decided and why. This is the single most useful tool for tuning triggers and priorities.

---

## When to use semantic routing

Install the optional extra:
```bash
pip install cyrrus[embeddings]
```

Use `EmbeddingRouter` when your users phrase things in ways your keyword triggers will never catch:

```python
from cyrrus.embedding_router import EmbeddingRouter

router = EmbeddingRouter(config)
bot = Projector(config, llm_call=my_llm, router=router)
```

Now the `examples` field in your slide config actually gets used — matched by meaning, not literal words:

```python
"weather_tool": {
    "content": "Weather lookup active.",
    "triggers": ["weather", "forecast"],           # keyword fallback
    "examples": ["should I bring an umbrella", "is it cold out"],  # semantic matching
}
```

**Tradeoff:** ~120MB extra install, a real (small) model download on first run, and slightly slower routing. Worth it if your triggers keep missing real user phrasing — check your traces to know for sure before adding the dependency.

---

## Common mistakes

**Using `session_id="default"` for every user.** Covered above. Don't.

**Setting `active_turns` too low for a naturally long topic.** If your coding lens fades after 1 turn but debugging sessions run 5+ turns, users will notice the formatting instruction silently dropping mid-conversation. Match `active_turns` to how long the topic actually lasts.

**Too few triggers.** One trigger word per slide guarantees you'll miss most real phrasing. Cast a wider net.

**Setting `max_context_tokens` too low with tools enabled.** Tool slides reserve `tool_estimate_tokens` upfront. If your budget is tight and you have multiple tools, they'll compete hard for space — check the trace to see what's getting dropped.

**Forgetting `fact_extractor=None` when you don't want memory.** If your app has no concept of returning users, disable the extractor rather than letting it silently accumulate facts you'll never use.

**Assuming keyword routing catches everything.** It won't. It's fast and free, but it only matches literal words. If your users' phrasing regularly misses your triggers, that's the signal to add `cyrrus[embeddings]`.

---

## Production checklist

- [ ] Every user has a unique `session_id`
- [ ] `max_context_tokens` is sized appropriately for your model's context window
- [ ] Tool slides have realistic `tool_estimate_tokens` values
- [ ] `active_turns` is set thoughtfully per slide, not left at the global default everywhere
- [ ] You've looked at `bot.last_trace` at least once to confirm routing does what you expect
- [ ] If handling sensitive data, you know `MemoryVault.delete_session()` exists
- [ ] You've decided whether you need `cyrrus[embeddings]` based on real user phrasing, not guesswork
- [ ] Your `llm_call` function handles its own provider-side errors gracefully

---

*Questions, bugs, or ideas? Open an issue on [GitHub](https://github.com/kikusuka/cyrrus).*
