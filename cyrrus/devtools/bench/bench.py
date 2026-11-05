#!/usr/bin/env python3
"""
cyrrus context-injection benchmark (stdlib only, deterministic, offline).

WHAT THIS MEASURES
------------------
This measures **injection quality**: which stored facts each strategy puts into
the model's context for a given query. It does NOT measure model answer quality
-- no LLM is called and no answers are graded. Recall / stale-leak / token
counts describe the context that *would* be injected.

Three strategies are compared on identical scenarios:

  full_dump   -- inject every stored fact row (session-agnostic, uncapped).
                 The "send everything every time" baseline.
  recent_n    -- inject the N most-recently-stored fact rows (global recency
                 window, N = MAX_FACTS). Recency, not relevance.
  cyrrus      -- the real cyrrus default: MemoryVault.retrieve(), i.e. BM25
                 relevance ranking over all active facts for the session,
                 capped at MAX_FACTS. This is exactly the mechanism
                 Projector._prepare_turn uses to inject user facts.

Metrics (aggregated per scenario):
  recall          -- mean fraction of needed facts present in injected context
                     (1.0 = every needed fact was injected). Higher is better.
  stale_leak      -- total count of forbidden facts injected across probes:
                     superseded values, expired old-topic facts, or another
                     user's facts. Lower is better (0 = clean).
  injected_tokens -- mean injected fact tokens per probe. Lower is better.

Determinism: fixed RNG seed, no network, no LLM, no wall-clock-dependent logic.
Runtime target: well under 60 seconds (dominated by the 5,000-row scenario).

Run:
    python devtools/bench/bench.py            # table to stdout + JSON alongside
    python devtools/bench/bench.py --json out.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import sys
import tempfile
import time

# Allow running from a source checkout without installation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(os.path.dirname(_HERE))  # .../cyrrus (project root)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from cyrrus.memory import MemoryVault  # noqa: E402

SEED = 1234
MAX_FACTS = 5          # injection budget for recent_n and cyrrus
DISTRACTOR_SIZES = [50, 500, 5000]


# --------------------------------------------------------------------------- #
# Token estimate (identical for all three systems, for fairness)
# --------------------------------------------------------------------------- #
def fact_tokens(keyword: str, value: str) -> int:
    text = keyword.replace("_", " ") + " " + str(value)
    return len(text.split())


# --------------------------------------------------------------------------- #
# Fact store: a real MemoryVault (for cyrrus) + an ordered row log (baselines)
# --------------------------------------------------------------------------- #
class FactStore:
    def __init__(self, db_dir: str):
        self.db_path = os.path.join(db_dir, "bench.db")
        self.vault = MemoryVault(db_path=self.db_path)
        # Ordered log of every row ever stored: (session, keyword, value).
        # Includes superseded values, so baselines can leak stale facts.
        self.log = []

    async def store(self, session: str, keyword: str, value: str):
        await self.vault.upsert(session, keyword, str(value),
                                fact_tokens(keyword, value))
        self.log.append((session, keyword, str(value)))


# --------------------------------------------------------------------------- #
# Injection strategies -> list of (keyword, value) pairs
# --------------------------------------------------------------------------- #
async def inject_full_dump(store: FactStore, session: str, query: str):
    # "Everything": every stored row, ignoring session and budget.
    return [(kw, val) for (_s, kw, val) in store.log]


async def inject_recent_n(store: FactStore, session: str, query: str):
    # Global most-recent-N window over stored rows.
    return [(kw, val) for (_s, kw, val) in store.log[-MAX_FACTS:]]


async def inject_cyrrus(store: FactStore, session: str, query: str):
    # Real cyrrus default: BM25 relevance over all active facts, capped.
    slides = await store.vault.retrieve(session, query, limit=MAX_FACTS)
    pairs = []
    for s in slides:
        kw = s.id[len("mem_"):] if s.id.startswith("mem_") else s.id
        val = s.content
        if val.startswith("Fact: "):
            val = val[len("Fact: "):]
        pairs.append((kw, val))
    return pairs


SYSTEMS = {
    "full_dump": inject_full_dump,
    "recent_n": inject_recent_n,
    "cyrrus": inject_cyrrus,
}


# --------------------------------------------------------------------------- #
# Scenario building blocks
# --------------------------------------------------------------------------- #
def store_step(session, keyword, value):
    return {"op": "store", "session": session, "keyword": keyword, "value": value}


def probe_step(session, query, need, forbidden):
    # need: {keyword: expected_value}; forbidden: [(keyword, value), ...]
    return {"op": "probe", "session": session, "query": query,
            "need": need, "forbidden": forbidden}


def distractors(session, n, rng):
    """n filler facts that intentionally do NOT match benchmark queries."""
    topics = ["weather", "traffic", "groceries", "calendar", "hardware",
              "shipping", "invoice", "meeting", "backup", "release"]
    steps = []
    for i in range(n):
        t = topics[rng.randrange(len(topics))]
        steps.append(store_step(session, "note_%05d" % i,
                                "unrelated filler record %d about %s" % (i, t)))
    return steps


def build_scenarios():
    rng = random.Random(SEED)
    scenarios = []

    # 1. Updated fact: Porto supersedes Lisbon; the stale value must not leak.
    scenarios.append({
        "name": "updated_fact",
        "steps": [
            store_step("s", "user_location", "Lisbon"),
            store_step("s", "user_location", "Porto"),
            probe_step("s", "where do I live?",
                       need={"user_location": "Porto"},
                       forbidden=[("user_location", "Lisbon")]),
        ],
    })

    # 2. Buried old fact among N distractors (relevance vs recency).
    for n in DISTRACTOR_SIZES:
        steps = [store_step("s", "user_location", "Lisbon")]
        steps += distractors("s", n, rng)
        steps.append(probe_step("s", "where do I live?",
                                need={"user_location": "Lisbon"},
                                forbidden=[]))
        scenarios.append({"name": "buried_%d" % n, "steps": steps})

    # 3. Topic switch: old-topic fact must expire from the injected context.
    scenarios.append({
        "name": "topic_switch",
        "steps": [
            store_step("s", "user_project", "AlphaApp"),
            store_step("s", "user_language", "Python"),
            probe_step("s", "what language do I use?",
                       need={"user_language": "Python"},
                       forbidden=[("user_project", "AlphaApp")]),
        ],
    })

    # 4. Preference recall with the preference buried under distractors.
    steps = [store_step("s", "user_preference", "dark mode")]
    steps += distractors("s", 20, rng)
    steps.append(probe_step("s", "what do I prefer?",
                            need={"user_preference": "dark mode"},
                            forbidden=[]))
    scenarios.append({"name": "preference_recall", "steps": steps})

    # 5. Multiple users: no cross-user leakage. Alice's facts must be recalled
    #    for Alice's query; Bob's facts must never appear.
    steps = [
        store_step("alice", "user_name", "Alice"),
        store_step("alice", "user_city", "Paris"),
        store_step("bob", "user_name", "Bob"),
        store_step("bob", "user_city", "Berlin"),
    ]
    steps += distractors("bob", 6, rng)  # push Alice out of the recent window
    steps.append(probe_step("alice", "what is my name and city?",
                            need={"user_name": "Alice", "user_city": "Paris"},
                            forbidden=[("user_name", "Bob"),
                                       ("user_city", "Berlin")]))
    scenarios.append({"name": "multi_user", "steps": steps})

    return scenarios


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def score_probe(injected, need, forbidden):
    injected_set = set(injected)
    if need:
        found = sum(1 for kv in need.items() if kv in injected_set)
        recall = found / len(need)
    else:
        recall = 1.0
    stale_leak = sum(1 for kv in forbidden if kv in injected_set)
    tokens = sum(fact_tokens(kw, val) for kw, val in injected)
    return recall, stale_leak, tokens


async def run_scenario(scenario):
    db_dir = tempfile.mkdtemp(prefix="cyrrus_bench_")
    try:
        store = FactStore(db_dir)
        acc = {name: {"recall": [], "stale_leak": 0, "tokens": []}
               for name in SYSTEMS}
        for step in scenario["steps"]:
            if step["op"] == "store":
                await store.store(step["session"], step["keyword"], step["value"])
            elif step["op"] == "probe":
                for name, inject in SYSTEMS.items():
                    injected = await inject(store, step["session"], step["query"])
                    r, leak, tok = score_probe(injected, step["need"],
                                               step["forbidden"])
                    acc[name]["recall"].append(r)
                    acc[name]["stale_leak"] += leak
                    acc[name]["tokens"].append(tok)
        result = {}
        for name in SYSTEMS:
            recalls = acc[name]["recall"] or [0.0]
            toks = acc[name]["tokens"] or [0]
            result[name] = {
                "recall": round(sum(recalls) / len(recalls), 3),
                "stale_leak": acc[name]["stale_leak"],
                "injected_tokens": round(sum(toks) / len(toks), 1),
            }
        return result
    finally:
        shutil.rmtree(db_dir, ignore_errors=True)


async def run_all():
    scenarios = build_scenarios()
    out = {}
    for sc in scenarios:
        out[sc["name"]] = await run_scenario(sc)
    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
DISCLAIMER = (
    "Measures injection quality (which stored facts enter the context), "
    "NOT model answer quality. No LLM is called."
)


def to_markdown(results):
    lines = []
    lines.append("# cyrrus context-injection benchmark")
    lines.append("")
    lines.append("> " + DISCLAIMER)
    lines.append("")
    lines.append("recall: higher is better (1.0 = every needed fact injected). "
                 "stale_leak: lower is better (0 = no superseded/expired/"
                 "cross-user facts). injected_tokens: mean per probe, lower is "
                 "better. Budget for recent_n and cyrrus = %d facts." % MAX_FACTS)
    lines.append("")
    lines.append("| scenario | system | recall | stale_leak | injected_tokens |")
    lines.append("|---|---|---|---|---|")
    for sc_name, systems in results.items():
        for sys_name in ("cyrrus", "recent_n", "full_dump"):
            m = systems[sys_name]
            lines.append("| %s | %s | %.3f | %d | %.1f |" % (
                sc_name, sys_name, m["recall"], m["stale_leak"],
                m["injected_tokens"]))
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    default_json = os.path.join(_HERE, "bench_results.json")
    ap.add_argument("--json", default=default_json,
                    help="path to write JSON results (default: %(default)s)")
    args = ap.parse_args()

    start = time.time()
    results = asyncio.run(run_all())
    elapsed = time.time() - start

    md = to_markdown(results)
    print(md)
    print("Total benchmark time: %.1fs (seed=%d, offline, no LLM)." % (elapsed, SEED))

    payload = {
        "disclaimer": DISCLAIMER,
        "seed": SEED,
        "max_facts": MAX_FACTS,
        "elapsed_s": round(elapsed, 2),
        "results": results,
    }
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print("JSON written to %s" % args.json)


if __name__ == "__main__":
    main()
