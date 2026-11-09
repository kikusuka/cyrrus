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

## Holdout

`holdout.py` is a separate set of **holdout scenarios, never used to pick
defaults**. It is an out-of-sample recall/token check run alongside `bench.py`;
defaults are chosen on `bench.py` and the joint sweep, not on the holdout.

```
python devtools/bench/holdout.py                       # v8 defaults
python devtools/bench/holdout.py max_df_fraction=1.0   # override a v8 param
```

## What it measures

For each scenario the harness stores facts, then issues probe queries and checks
what each strategy would inject into the model context:

- **recall** — mean fraction of *needed* facts present in the injected context
  (1.0 = every needed fact was injected). Higher is better.
- **stale_leak** — total count of *forbidden* facts injected across the
  scenario's probes: superseded values, expired old-topic facts, or another
  user's facts. Lower is better (0 = clean).
- **injected_tokens** — mean injected fact tokens per probe. Lower is better.
- **injected_facts** — mean NUMBER of facts injected per probe, i.e. how much of
  the `MAX_FACTS` context budget was actually spent.
- **distractor_rate** — mean **share of the injected facts that are KNOWN planted
  noise** for each probe (the filler notes / near-duplicate look-alikes the
  scenario deliberately stores). This is a *precision* measure, orthogonal to
  recall: a probe can reach **recall 1.0** — the needed fact is present — while
  the rest of its budget is filled with distractors. Computed per probe as
  (injected facts whose keyword is a planted distractor) / (injected facts),
  0.0 when nothing was injected. Lower is better. `near_dup_30` is the case this
  exists for: recall alone said cyrrus "passed"; distractor_rate shows it mostly
  padded the context with look-alike cities.
- **known_weak** — list of reasons cyrrus currently fails the scenario
  (recall < 1.0, stale_leak > 0, **or distractor_rate >= `DISTRACTOR_WEAK`
  (0.50)** — i.e. at least half the injected facts are known noise). Shown in the
  table as `[known-weak: ...]`.

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
  surface for three paraphrases of the same need (`where do I live`, `which city
  am I in`, `where am I based`) against **30 competing look-alike facts** about
  *other* cities. Each look-alike is stored under a topically city/home-flavoured
  key cycling through `user_hometown` / `user_birthplace` / `user_previous_city` /
  `user_work_city` (disambiguated with a per-city slug so all 30 stay simultaneously
  active — supersession is per `(session, keyword)`), and its **value** reuses the
  `live`/`city`/`home` vocabulary (`"<city> is a city where people live and own a
  home"`), so it lexically crowds the true fact.
  What `distractor_rate` reveals here, which recall alone hid: cyrrus reaches
  **recall 1.0** (the Porto fact is present for every query — `user_location`'s
  `location` alias head `live … city … based` and the query's first-person `I` lift
  it in), but it marks the scenario **`[known-weak]` on precision**: measured
  `distractor_rate = 0.800`, i.e. 4 of the 5 injected facts are look-alike cities.
  `bm25_all` scores the same; `recent_n` fails outright (recall 0 — Porto stored
  first, then buried). The distractor keys are **not** token-boosted by `KEY_ALIASES`
  (only the head `location` is), so this is not rigged for or against cyrrus —
  `where am I based` in particular leans on the `based` alias the true fact
  uniquely carries. Numbers are reported as measured; cyrrus is not tuned to win.
- `correction_different_key` — "I no longer like pizza" stored under a NEW
  keyword: same-key supersession does not retire the old preference, so the
  stale fact remains injectable. Currently known-weak for every system.

## How to add a scenario

Edit `build_scenarios()` in `bench.py`. A scenario is a dict with a `name` and a
list of `steps`. Steps are built with two helpers:

```python
store_step(session, keyword, value)                     # store/supersede a fact
probe_step(session, query, need, forbidden, distractors)  # evaluate one query
distractors(session, n, rng) -> (steps, keyword_list)   # n planted noise facts
```

- `need` is a `{keyword: expected_value}` dict — every pair must be injected for
  full recall.
- `forbidden` is a list of `(keyword, value)` pairs that must **not** be
  injected (superseded values, expired topics, other users' facts). Each
  forbidden pair that shows up counts as one `stale_leak`.
- `distractors` is the list of keywords returned by `distractors(...)` (or a
  hand-built list, as in `near_dup_30`) naming the KNOWN noise for that probe;
  it drives `distractor_rate`. Pass `[]` when the scenario has no planted noise.

Example — add a hobby fact buried under 30 distractors:

```python
def build_scenarios():
    rng = random.Random(SEED)
    scenarios = [ ... ]  # existing scenarios

    steps = [store_step("s", "user_hobby", "woodworking")]
    fill, fill_kws = distractors("s", 30, rng)
    steps += fill
    steps.append(probe_step(
        "s", "what is my hobby?",
        need={"user_hobby": "woodworking"},
        forbidden=[],
        distractors=fill_kws,
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
