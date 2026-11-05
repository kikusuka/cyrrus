# cyrrus injection benchmark

Deterministic, offline, standard-library-only benchmark that compares **context
injection strategies** — not model answers. No LLM is called and no network is
used. A full run (quality scenarios + latency at 1k/5k/50k facts) finishes in
about a minute.

> **Honesty note.** This harness measures *injection quality* — which stored
> facts each strategy would put into the model's context — **not** answer
> quality. It is written and maintained by the same team as the cyrrus fixes it
> compares against, so treat cross-system numbers with that bias in mind.
> Scenarios cyrrus currently fails are marked `[known-weak]` in the output
> instead of being hidden.

Run it with the project's interpreter (editable install or source checkout):

```
python devtools/bench/bench.py                 # prints markdown tables
python devtools/bench/bench.py --json out.json # choose the JSON output path
```

It prints markdown tables to stdout and writes `bench_results.json` next to
`bench.py` by default.

## What it measures

For each scenario the harness stores facts, then issues probe queries and checks
what each strategy would inject into the model context:

- **recall** — mean fraction of *needed* facts present in the injected context
  (1.0 = every needed fact was injected). Higher is better.
- **stale_leak** — total count of *forbidden* facts injected across the
  scenario's probes: superseded values, expired old-topic facts, or another
  user's facts. Lower is better (0 = clean).
- **injected_tokens** — mean injected fact tokens per probe. Lower is better.
- **known_weak** — list of reasons cyrrus currently fails the scenario
  (recall < 1.0 or stale_leak > 0). Shown in the table as `[known-weak: ...]`.

The latency section reports **median / p95 / first-call** milliseconds per
retrieve at 1,000 / 5,000 / 50,000 stored facts for every strategy. **All four
strategies read from the same SQLite store** (the `bench.db` file): cyrrus
through its own persistent `MemoryVault` connection with a cached per-session
index, the three baselines through one shared read connection on the same file.
This is the fair comparison because cyrrus's real retrieval path is
SQLite-backed. (The *quality* section above instead reads an in-memory row log,
which is fine there because it only measures *which* facts are injected, not how
fast — every strategy sees the identical set of stored rows.) Facts are
bulk-inserted through a second SQLite connection, which also exercises cyrrus's
cross-connection staleness detection. cyrrus's `first_call` includes the cold
per-session index build (~2s at 50k); warm retrieves reuse the index. Note that
reading from SQLite makes `full_dump`'s true cost visible — fetching every row
per probe is ~193ms at 50k, not the ~27ms an in-memory list would suggest.
Probe queries deliberately include high-frequency terms that match most rows, so
the numbers reflect a near-worst case for the inverted index, not just easy
queries.

## Strategies compared

| system | behavior |
|---|---|
| `full_dump` | inject every stored row, session-agnostic and uncapped ("send everything") |
| `recent_n` | inject the `MAX_FACTS` most-recently-stored rows globally (recency window) |
| `bm25_all` | plain BM25 over every row ever stored for the session, **no supersession** — stale/superseded versions stay rankable. Isolates what cyrrus's temporal layer adds on top of the same ranking function |
| `cyrrus` | the real cyrrus default: `MemoryVault.retrieve()` — BM25 relevance over all *active* facts for the session (per-session inverted index), capped at `MAX_FACTS` |

`cyrrus` drives the actual retrieval code `Projector._prepare_turn` uses, so its
numbers reflect real cyrrus behavior. The baselines are intentionally naive
strategies. In the quality scenarios they read the same in-memory row log cyrrus
sees (including superseded rows, which is what lets the naive strategies leak
stale facts); in the latency section all four read the same SQLite store.

## Scenarios

- `updated_fact` — Porto supersedes Lisbon; the stale value must not leak.
- `buried_50` / `buried_500` / `buried_5000` — a relevant fact stored first,
  then buried under N unrelated distractors; relevance must beat recency.
- `topic_switch` — a real topic switch: the conversation moves from travel
  planning (topic A: `plan a trip to Rome`, `book a hotel …`) to dinner planning
  (topic B: `plan a dinner party …`), then a topic-B query (`help me plan the
  dinner`) must not re-inject the stale topic-A facts. cyrrus has **no
  temporal/topic expiry** — it is lexical BM25 over all active facts — so tokens
  shared across topics (`plan`, `the`) pull the old-topic facts back in. This is
  `[known-weak]` for cyrrus (stale_leak 2), and *every* strategy fails it the
  same way; none of them model topic expiry.
- `preference_recall` — a preference buried under distractors must still surface.
- `multi_user` — Alice's query must recall Alice's facts and never inject Bob's.
- `paraphrase_no_overlap` — 12 store/probe pairs where the query shares **no
  token** with the fact's keyword, its `KEY_ALIASES` expansion, or its value.
  Lexical BM25 cannot bridge these: cyrrus and `bm25_all` score 0 (known-weak);
  the recency/dump strategies "win" only because they inject everything.
- `near_dup_30` — a single true fact `user_location = "I live in Porto"` must
  survive 30 distractor facts about *other* cities that deliberately reuse the
  `live`/`city`/`home` vocabulary (`"<city> is a city where people live and own
  a home"`), for the question `where do I live?`. **cyrrus passes this as
  specified** — and we report that plainly rather than dressing it up as a
  failure. Two real cyrrus behaviors lift the true fact above the 30 look-alikes:
  (1) the `user_location` keyword expands via `KEY_ALIASES` to `live living home
  city …`, while the plain `city_note_*` distractor keywords get no such boost;
  and (2) the query's first-person `I` matches only the true fact (high IDF).
  `recent_n` fails it (recall 0) because Porto is stored first and then buried
  under the 30 cities. This scenario is the faithful rewrite of the earlier
  near-duplicate report; the earlier failure is **not** reproduced under this
  exact spec, and that is stated rather than hidden.
- `correction_different_key` — "I no longer like pizza" stored under a NEW
  keyword: same-key supersession does not retire the old preference, so the
  stale fact remains injectable. Currently known-weak for every system.

## How to add a scenario

Edit `build_scenarios()` in `bench.py`. A scenario is a dict with a `name` and a
list of `steps`. Steps are built with two helpers:

```python
store_step(session, keyword, value)          # store/supersede a fact
probe_step(session, query, need, forbidden)  # evaluate injection for a query
```

- `need` is a `{keyword: expected_value}` dict — every pair must be injected for
  full recall.
- `forbidden` is a list of `(keyword, value)` pairs that must **not** be
  injected (superseded values, expired topics, other users' facts). Each
  forbidden pair that shows up counts as one `stale_leak`.

Example — add a hobby fact buried under 30 distractors:

```python
def build_scenarios():
    rng = random.Random(SEED)
    scenarios = [ ... ]  # existing scenarios

    steps = [store_step("s", "user_hobby", "woodworking")]
    steps += distractors("s", 30, rng)
    steps.append(probe_step(
        "s", "what is my hobby?",
        need={"user_hobby": "woodworking"},
        forbidden=[],
    ))
    scenarios.append({"name": "buried_hobby", "steps": steps})
    return scenarios
```

Guidelines:

- Keep it deterministic: draw any filler from the passed-in `rng`
  (`random.Random(SEED)`); never use time, randomness, or the network directly.
- Choose probe queries whose words match the fact's keyword or its alias set in
  `cyrrus/bm25.py` (`KEY_ALIASES`) when you want lexical retrieval to have a
  fair chance; for paraphrase-style scenarios, verify NO query token overlaps
  the expanded keyword or the value, and expect a `[known-weak]` mark.
  Distractor text should deliberately avoid the query terms.
- Do not tune scenarios so cyrrus wins. If cyrrus fails a scenario, leave it in
  and let the `[known-weak]` marking show it.
- Keep the total runtime sane (~60s today); the `buried_5000` stores and the 50k
  latency section dominate. `bm25_all` re-ranks the whole log per probe, so
  large scenarios are the expensive ones.
- Use a distinct `session` per user when testing isolation; `full_dump` and
  `recent_n` ignore sessions on purpose, which is what surfaces cross-user leaks.
