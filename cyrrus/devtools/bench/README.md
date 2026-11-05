# cyrrus injection benchmark

Deterministic, offline, standard-library-only benchmark that compares **context
injection strategies** — not model answers. No LLM is called and no network is
used. A full run finishes in well under 60 seconds (the 5,000-row scenario
dominates).

Run it with the project's interpreter (editable install or source checkout):

```
python devtools/bench/bench.py                 # prints a markdown table
python devtools/bench/bench.py --json out.json # choose the JSON output path
```

It prints a markdown table to stdout and writes `bench_results.json` next to
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

## Strategies compared

| system | behavior |
|---|---|
| `full_dump` | inject every stored row, session-agnostic and uncapped ("send everything") |
| `recent_n` | inject the `MAX_FACTS` most-recently-stored rows globally (recency window) |
| `cyrrus` | the real cyrrus default: `MemoryVault.retrieve()` — BM25 relevance over all active facts for the session, capped at `MAX_FACTS` |

`cyrrus` drives the actual retrieval code `Projector._prepare_turn` uses, so its
numbers reflect real cyrrus behavior. The two baselines are intentionally naive
strategies that read the same stored row log.

## Scenarios

- `updated_fact` — Porto supersedes Lisbon; the stale value must not leak.
- `buried_50` / `buried_500` / `buried_5000` — a relevant fact stored first,
  then buried under N unrelated distractors; relevance must beat recency.
- `topic_switch` — after moving to a new topic, the old-topic fact must not be
  injected for a new-topic query (ghost/old context expiry).
- `preference_recall` — a preference buried under distractors must still surface.
- `multi_user` — Alice's query must recall Alice's facts and never inject Bob's.

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
  `cyrrus/bm25.py` (`KEY_ALIASES`), otherwise BM25 cannot surface it. Distractor
  text should deliberately avoid the query terms.
- Keep the total runtime under ~60s; large `buried_*` scenarios dominate because
  each stored fact is a separate SQLite write.
- Use a distinct `session` per user when testing isolation; `full_dump` and
  `recent_n` ignore sessions on purpose, which is what surfaces cross-user leaks.
