#!/usr/bin/env python3
"""
cyrrus context-injection benchmark (stdlib only, deterministic, offline).

WHAT THIS MEASURES
------------------
This measures **injection quality**: which stored facts each strategy puts into
the model's context for a given query. It does NOT measure model answer quality
-- no LLM is called and no answers are graded. Recall / stale-leak / token
counts describe the context that *would* be injected.

Four strategies are compared on identical scenarios:

  full_dump   -- inject every stored fact row (session-agnostic, uncapped).
                 The "send everything every time" baseline.
  recent_n    -- inject the N most-recently-stored fact rows (global recency
                 window, N = MAX_FACTS). Recency, not relevance.
  bm25_all    -- plain BM25 over every row ever stored for the session, with
                 NO supersession: stale/superseded versions stay rankable.
                 Isolates what the temporal layer contributes on top of BM25.
  cyrrus      -- the real cyrrus default: MemoryVault.retrieve(), i.e. BM25
                 relevance ranking over all active facts for the session,
                 capped at MAX_FACTS. This is exactly the mechanism
                 Projector._prepare_turn uses to inject user facts.

Scenarios where cyrrus currently fails (recall < 1.0 or stale_leak > 0) are
marked "known-weak" in the output instead of being hidden.

Metrics (aggregated per scenario):
  recall          -- mean fraction of needed facts present in injected context
                     (1.0 = every needed fact was injected). Higher is better.
  stale_leak      -- total count of forbidden facts injected across probes:
                     superseded values, expired old-topic facts, or another
                     user's facts. Lower is better (0 = clean).
  injected_tokens -- mean injected fact tokens per probe. Lower is better.
  injected_facts  -- mean NUMBER of facts injected per probe (how much of the
                     context budget was actually spent).
  distractor_rate -- mean share of the injected facts that are KNOWN planted
                     noise (filler notes / near-duplicate look-alikes), per
                     probe. Precision, not recall: a probe can reach recall 1.0
                     while filling most of its budget with distractors. Lower is
                     better; cyrrus at/above DISTRACTOR_WEAK is marked known-weak.

A separate latency section reports median / p95 / first-call wall time per
retrieve at 1k / 5k / 50k stored facts for every strategy.

Determinism: fixed RNG seed, no network, no LLM, no wall-clock-dependent logic
(wall-clock is only *measured* in the latency section, never branched on).

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
import sqlite3
import statistics
import sys
import tempfile
import time

# Allow running from a source checkout without installation.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(os.path.dirname(_HERE))  # .../cyrrus (project root)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from cyrrus.bm25 import bm25_rank_facts  # noqa: E402
from cyrrus.memory import MemoryVault  # noqa: E402

SEED = 1234
MAX_FACTS = 5          # injection budget for recent_n, bm25_all and cyrrus
DISTRACTOR_WEAK = 0.5  # cyrrus distractor_rate at/above this = known-weak (poor precision)
DISTRACTOR_SIZES = [50, 500, 5000]
LATENCY_SIZES = [1000, 5000, 50000]
LATENCY_PROBES = 10
SYSTEM_ORDER = ("cyrrus", "bm25_all", "recent_n", "full_dump")


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


async def inject_bm25_all(store: FactStore, session: str, query: str):
    # Plain BM25 over every row EVER stored for the session, with no
    # supersession: stale/superseded versions remain rankable. This isolates
    # what cyrrus's temporal layer adds on top of the same ranking function.
    facts = [(kw, val, fact_tokens(kw, val))
             for (s, kw, val) in store.log if s == session]
    ranked = bm25_rank_facts(facts, query, limit=MAX_FACTS, score_threshold=0.0)
    return [(kw, val) for (_score, kw, val, _tok) in ranked]


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
    "bm25_all": inject_bm25_all,
    "cyrrus": inject_cyrrus,
}


# --------------------------------------------------------------------------- #
# Scenario building blocks
# --------------------------------------------------------------------------- #
def store_step(session, keyword, value):
    return {"op": "store", "session": session, "keyword": keyword, "value": value}


def probe_step(session, query, need, forbidden, distractors=()):
    # need: {keyword: expected_value}; forbidden: [(keyword, value), ...];
    # distractors: iterable of keywords planted as KNOWN noise for this probe,
    # used to compute distractor_rate (share of injected facts that are noise).
    return {"op": "probe", "session": session, "query": query,
            "need": need, "forbidden": forbidden,
            "distractors": frozenset(distractors)}


def distractors(session, n, rng):
    """n filler facts that intentionally do NOT match benchmark queries.

    Returns (steps, keyword_set) so the probe can score distractor_rate.
    """
    topics = ["weather", "traffic", "groceries", "calendar", "hardware",
              "shipping", "invoice", "meeting", "backup", "release"]
    steps = []
    kws = []
    for i in range(n):
        t = topics[rng.randrange(len(topics))]
        kw = "note_%05d" % i
        steps.append(store_step(session, kw,
                                "unrelated filler record %d about %s" % (i, t)))
        kws.append(kw)
    return steps, kws


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
        fill, fill_kws = distractors("s", n, rng)
        steps += fill
        steps.append(probe_step("s", "where do I live?",
                                need={"user_location": "Lisbon"},
                                forbidden=[], distractors=fill_kws))
        scenarios.append({"name": "buried_%d" % n, "steps": steps})

    # 3. Topic switch with old-topic expiry. The conversation moves from
    #    travel planning (topic A) to dinner planning (topic B); after the
    #    switch a topic-B query must NOT re-inject the stale topic-A facts.
    #    cyrrus has no temporal/topic expiry -- it is lexical BM25 over all
    #    active facts -- so any token shared across topics ("plan", "the")
    #    pulls the old-topic facts back into the context. cyrrus is expected
    #    to fail here (known-weak, stale_leak > 0); every strategy compared
    #    fails the same way because none of them model topic expiry.
    scenarios.append({
        "name": "topic_switch",
        "steps": [
            # topic A: travel planning (stale once the conversation moves on)
            store_step("s", "user_trip", "plan a trip to Rome in May"),
            store_step("s", "user_hotel", "book a hotel near the Colosseum"),
            # topic B: dinner planning (where the conversation has moved)
            store_step("s", "user_dinner", "plan a dinner party on Saturday"),
            store_step("s", "user_recipe", "cook a lasagna for the party"),
            probe_step("s", "help me plan the dinner",
                       need={"user_dinner": "plan a dinner party on Saturday"},
                       forbidden=[("user_trip", "plan a trip to Rome in May"),
                                  ("user_hotel",
                                   "book a hotel near the Colosseum")]),
        ],
    })

    # 4. Preference recall with the preference buried under distractors.
    steps = [store_step("s", "user_preference", "dark mode")]
    fill, fill_kws = distractors("s", 20, rng)
    steps += fill
    steps.append(probe_step("s", "what do I prefer?",
                            need={"user_preference": "dark mode"},
                            forbidden=[], distractors=fill_kws))
    scenarios.append({"name": "preference_recall", "steps": steps})

    # 5. Multiple users: no cross-user leakage. Alice's facts must be recalled
    #    for Alice's query; Bob's facts must never appear.
    steps = [
        store_step("alice", "user_name", "Alice"),
        store_step("alice", "user_city", "Paris"),
        store_step("bob", "user_name", "Bob"),
        store_step("bob", "user_city", "Berlin"),
    ]
    fill, fill_kws = distractors("bob", 6, rng)  # push Alice out of the recent window
    steps += fill
    steps.append(probe_step("alice", "what is my name and city?",
                            need={"user_name": "Alice", "user_city": "Paris"},
                            forbidden=[("user_name", "Bob"),
                                       ("user_city", "Berlin")],
                            distractors=fill_kws))
    scenarios.append({"name": "multi_user", "steps": steps})

    # 6. Paraphrase: queries deliberately share NO token with the stored
    #    fact's keyword, its KEY_ALIASES expansion, or its value. Lexical
    #    BM25 cannot bridge these; cyrrus is expected to fail (known-weak).
    #    Cases are interleaved store/probe so each probe sees only facts
    #    stored up to that point (checked: no query token matches any
    #    earlier fact's document either).
    paraphrase_cases = [
        ("user_favorite_drink", "espresso",
         "what beverage do I order every morning?"),
        ("car_model", "Subaru Outback",
         "which vehicle am I driving these days?"),
        ("residence_town", "Braga",
         "which municipality do I reside in?"),
        ("married_to", "Marta",
         "which person did I wed?"),
        ("daily_routine", "runs at dawn",
         "what exercise do I do when the sun rises?"),
        ("preferred_genre", "science fiction novels",
         "which books am I into?"),
        ("office_floor", "third floor",
         "on which storey is my desk?"),
        ("sibling_count", "two brothers",
         "how many relatives of mine are male?"),
        ("morning_meal", "oatmeal with berries",
         "what do I eat after waking up?"),
        ("evening_activity", "chess club",
         "what game do I play after dark?"),
        ("transportation_mode", "bicycle",
         "how do I commute each weekday?"),
        ("dream_destination", "Kyoto",
         "where would I travel someday?"),
    ]
    steps = []
    for kw, val, query in paraphrase_cases:
        steps.append(store_step("s", kw, val))
        steps.append(probe_step("s", query, need={kw: val}, forbidden=[]))
    scenarios.append({"name": "paraphrase_no_overlap", "steps": steps})

    # 7. Near-duplicate city look-alikes (the earlier reported failure). A single
    #    true fact "I live in Porto" (keyword user_location, whose KEY_ALIASES
    #    head "location" expands to live/home/city/from/based/residence) must be
    #    the top hit for three paraphrases of the same need, against 30 competing
    #    look-alike facts about OTHER cities. Each look-alike sits under a
    #    topically city/home-flavoured key (user_hometown / user_birthplace /
    #    user_previous_city / user_work_city, cycled) and its VALUE reuses the
    #    live/city/home vocabulary, so it lexically crowds the true fact. A unique
    #    city slug keeps every look-alike simultaneously active (supersession is
    #    per (session, keyword)), so all 30 are genuinely rankable. These distractor
    #    keys are NOT token-boosted by KEY_ALIASES (only "location" is), so this
    #    is not rigged in cyrrus's favour: the query "where am I based" leans on
    #    the "based" alias the true fact uniquely carries. The distractor_rate and
    #    per-query recall are reported as measured -- cyrrus is NOT tuned to win.
    other_cities = [
        "Madrid", "Berlin", "Vienna", "Dublin", "Oslo", "Rome", "Athens",
        "Dubrovnik", "Seville", "Ghent", "Lyon", "Turin", "Valencia",
        "Krakow", "Riga", "Tallinn", "Bologna", "Florence", "Naples",
        "Palermo", "Zurich", "Geneva", "Antwerp", "Utrecht", "Salzburg",
        "Innsbruck", "Nice", "Marseille", "Bilbao", "Copenhagen",
    ]
    look_alike_keys = [
        "user_hometown", "user_birthplace", "user_previous_city", "user_work_city",
    ]
    steps = [store_step("s", "user_location", "I live in Porto")]
    la_kws = []
    for i, c in enumerate(other_cities):
        fam = look_alike_keys[i % len(look_alike_keys)]
        kw = "%s_%s" % (fam, c.lower())
        steps.append(store_step(
            "s", kw,
            "%s is a city where people live and own a home" % c))
        la_kws.append(kw)
    for q in ("where do I live", "which city am I in", "where am I based"):
        steps.append(probe_step("s", q,
                                need={"user_location": "I live in Porto"},
                                forbidden=[], distractors=la_kws))
    scenarios.append({"name": "near_dup_30", "steps": steps})

    # 8. Different-key correction: "I no longer like pizza" gets stored under
    #    a NEW keyword; the old preference stays active because supersession
    #    only replaces the same (session, keyword). The stale fact remains
    #    injectable -- a known weakness of key-based supersession without a
    #    smarter extractor.
    scenarios.append({
        "name": "correction_different_key",
        "steps": [
            store_step("s", "user_preference", "likes pizza"),
            store_step("s", "user_disliked_food", "no longer likes pizza"),
            probe_step("s", "what food do I like?",
                       need={"user_disliked_food": "no longer likes pizza"},
                       forbidden=[("user_preference", "likes pizza")]),
        ],
    })

    return scenarios


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def score_probe(injected, need, forbidden, distractors=frozenset()):
    injected_set = set(injected)
    if need:
        found = sum(1 for kv in need.items() if kv in injected_set)
        recall = found / len(need)
    else:
        recall = 1.0
    stale_leak = sum(1 for kv in forbidden if kv in injected_set)
    tokens = sum(fact_tokens(kw, val) for kw, val in injected)
    # distractor_rate: share of the injected facts that are KNOWN planted noise.
    # Precision, not recall: a probe can hit recall 1.0 yet fill most of its
    # context budget with distractors. 0.0 when nothing was injected.
    injected_count = len(injected)
    distractor_hits = sum(1 for kw, _val in injected if kw in distractors)
    distractor_rate = (distractor_hits / injected_count
                       if injected_count else 0.0)
    return recall, stale_leak, tokens, distractor_rate, injected_count


async def run_scenario(scenario):
    db_dir = tempfile.mkdtemp(prefix="cyrrus_bench_")
    try:
        store = FactStore(db_dir)
        acc = {name: {"recall": [], "stale_leak": 0, "tokens": [],
                      "distractor_rate": [], "injected_count": []}
               for name in SYSTEMS}
        for step in scenario["steps"]:
            if step["op"] == "store":
                await store.store(step["session"], step["keyword"], step["value"])
            elif step["op"] == "probe":
                for name, inject in SYSTEMS.items():
                    injected = await inject(store, step["session"], step["query"])
                    r, leak, tok, drate, icount = score_probe(
                        injected, step["need"], step["forbidden"],
                        step.get("distractors", frozenset()))
                    acc[name]["recall"].append(r)
                    acc[name]["stale_leak"] += leak
                    acc[name]["tokens"].append(tok)
                    acc[name]["distractor_rate"].append(drate)
                    acc[name]["injected_count"].append(icount)
        result = {}
        for name in SYSTEMS:
            recalls = acc[name]["recall"] or [0.0]
            toks = acc[name]["tokens"] or [0]
            drates = acc[name]["distractor_rate"] or [0.0]
            counts = acc[name]["injected_count"] or [0]
            result[name] = {
                "recall": round(sum(recalls) / len(recalls), 3),
                "stale_leak": acc[name]["stale_leak"],
                "injected_tokens": round(sum(toks) / len(toks), 1),
                "distractor_rate": round(sum(drates) / len(drates), 3),
                "injected_facts": round(sum(counts) / len(counts), 1),
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
# Latency: median / p95 / first-call wall time per retrieve at scale.
#
# FAIRNESS: every strategy reads from the SAME SQLite store (the bench.db
# file), not from an in-memory list. cyrrus reads through its own persistent
# MemoryVault connection (with the cached per-session index); full_dump,
# recent_n and bm25_all read through one shared read-only connection opened on
# the same file. This is the honest comparison because cyrrus's real retrieval
# path is SQLite-backed -- the quality section above can use the in-memory row
# log because it only measures WHICH facts are injected, not how fast.
#
# Facts are bulk-inserted through a second SQLite connection, which also
# exercises cyrrus's cross-connection staleness detection (PRAGMA data_version)
# and makes cyrrus's first_call pay the cold index build.
# --------------------------------------------------------------------------- #
LAT_QUERIES = [
    "where do I live?",                      # matches one fact (small candidate set)
    "unrelated query about nothing stored",  # matches nothing
    "filler record about shipping",          # matches MANY notes (large postings)
    "note record filler unrelated",          # matches MANY notes (very common terms)
    "what is my name?",
]


def _make_lat_systems(base_conn):
    """SQLite-backed injection strategies for the latency section.

    All four read the same bench.db file: the three baselines through the
    shared `base_conn`, cyrrus through its own MemoryVault connection. Each
    returns a list of (keyword, value) pairs, matching the quality-section
    inject_* signature so the timing loop is identical.
    """
    async def lat_full_dump(store, session, query):
        rows = base_conn.execute("SELECT keyword, value FROM facts").fetchall()
        return [(kw, val) for kw, val in rows]

    async def lat_recent_n(store, session, query):
        rows = base_conn.execute(
            "SELECT keyword, value FROM facts ORDER BY rowid DESC LIMIT ?",
            (MAX_FACTS,)).fetchall()
        return [(kw, val) for kw, val in rows]

    async def lat_bm25_all(store, session, query):
        rows = base_conn.execute(
            "SELECT keyword, value, tokens FROM facts WHERE session_id = ?",
            (session,)).fetchall()
        ranked = bm25_rank_facts(rows, query, limit=MAX_FACTS,
                                 score_threshold=0.0)
        return [(kw, val) for (_s, kw, val, _t) in ranked]

    return {
        "full_dump": lat_full_dump,
        "recent_n": lat_recent_n,
        "bm25_all": lat_bm25_all,
        "cyrrus": inject_cyrrus,
    }


async def run_latency():
    out = {}
    for n in LATENCY_SIZES:
        db_dir = tempfile.mkdtemp(prefix="cyrrus_bench_lat_")
        try:
            store = FactStore(db_dir)
            # One normal store creates the schema and the target fact.
            await store.store("s", "user_location", "Lisbon")

            rng = random.Random(SEED + n)
            topics = ["weather", "traffic", "groceries", "calendar", "hardware",
                      "shipping", "invoice", "meeting", "backup", "release"]
            base = time.time()
            rows = []
            for i in range(n - 1):
                kw = "note_%06d" % i
                val = "unrelated filler record %d about %s" % (
                    i, topics[rng.randrange(len(topics))])
                rows.append(("s", kw, val, fact_tokens(kw, val),
                             base + i * 0.001, "2026-01-01T00:00:00", None))
            conn = sqlite3.connect(store.db_path)
            conn.executemany(
                "INSERT INTO facts (session_id, keyword, value, tokens, "
                "last_accessed, valid_at, invalid_at) VALUES (?,?,?,?,?,?,?)",
                rows)
            conn.commit()
            conn.close()

            # All four strategies read the same SQLite file: baselines via
            # this shared read connection, cyrrus via its own vault connection.
            base_conn = sqlite3.connect(store.db_path)
            lat_systems = _make_lat_systems(base_conn)

            timings = {name: [] for name in lat_systems}
            for p in range(LATENCY_PROBES):
                q = LAT_QUERIES[p % len(LAT_QUERIES)]
                for name, inject in lat_systems.items():
                    t0 = time.perf_counter()
                    await inject(store, "s", q)
                    timings[name].append((time.perf_counter() - t0) * 1000.0)
            base_conn.close()

            out[str(n)] = {}
            for name in lat_systems:
                ts = sorted(timings[name])
                p95 = ts[max(0, int(len(ts) * 0.95) - 1)]
                out[str(n)][name] = {
                    "median_ms": round(statistics.median(ts), 2),
                    "p95_ms": round(p95, 2),
                    "first_call_ms": round(timings[name][0], 2),
                    "probes": len(ts),
                }
        finally:
            shutil.rmtree(db_dir, ignore_errors=True)
    return out


def known_weak_reasons(systems):
    """Why cyrrus currently fails this scenario (empty list = not weak)."""
    c = systems["cyrrus"]
    reasons = []
    if c["recall"] < 1.0:
        reasons.append("recall %.3f < 1.0" % c["recall"])
    if c["stale_leak"] > 0:
        reasons.append("stale_leak %d > 0" % c["stale_leak"])
    if c["distractor_rate"] >= DISTRACTOR_WEAK:
        reasons.append("distractor_rate %.3f >= %.2f (context mostly noise)"
                       % (c["distractor_rate"], DISTRACTOR_WEAK))
    return reasons


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
DISCLAIMER = (
    "Measures injection quality (which stored facts enter the context), "
    "NOT model answer quality. No LLM is called. This harness is written and "
    "maintained by the same team as the cyrrus fixes it compares against -- "
    "treat cross-system numbers with that bias in mind."
)


def to_markdown(results, latency):
    lines = []
    lines.append("# cyrrus context-injection benchmark")
    lines.append("")
    lines.append("> " + DISCLAIMER)
    lines.append("")
    lines.append("recall: higher is better (1.0 = every needed fact injected). "
                 "stale_leak: lower is better (0 = no superseded/expired/"
                 "cross-user facts). injected_tokens: mean per probe, lower is "
                 "better. injected_facts: mean number of facts injected per "
                 "probe (the context size actually spent). distractor_rate: mean "
                 "share of those injected facts that are KNOWN planted noise "
                 "(0.0 = clean precision, 1.0 = context is all noise) -- lower "
                 "is better; a probe can hit recall 1.0 yet pollute its budget. "
                 "Budget for recent_n, bm25_all and cyrrus = %d facts. "
                 "[known-weak] marks scenarios cyrrus currently fails "
                 "(recall < 1.0, stale_leak > 0, or distractor_rate >= %.2f); "
                 "they are shown, not hidden."
                 % (MAX_FACTS, DISTRACTOR_WEAK))
    lines.append("")
    lines.append("| scenario | system | recall | stale_leak | injected_tokens | injected_facts | distractor_rate |")
    lines.append("|---|---|---|---|---|---|---|")
    for sc_name, systems in results.items():
        weak = systems.get("known_weak", [])
        label = sc_name + (" [known-weak: %s]" % "; ".join(weak) if weak else "")
        for sys_name in SYSTEM_ORDER:
            m = systems[sys_name]
            lines.append("| %s | %s | %.3f | %d | %.1f | %.1f | %.3f |" % (
                label, sys_name, m["recall"], m["stale_leak"],
                m["injected_tokens"], m["injected_facts"], m["distractor_rate"]))
    lines.append("")
    lines.append("## Latency (ms per retrieve, %d probes each; first_call includes cold index build for cyrrus)" % LATENCY_PROBES)
    lines.append("")
    lines.append("| facts | system | median | p95 | first_call |")
    lines.append("|---|---|---|---|---|")
    for size in sorted(latency, key=int):
        for sys_name in SYSTEM_ORDER:
            m = latency[size][sys_name]
            lines.append("| %s | %s | %.2f | %.2f | %.2f |" % (
                size, sys_name, m["median_ms"], m["p95_ms"], m["first_call_ms"]))
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
    for sc_name, systems in results.items():
        systems["known_weak"] = known_weak_reasons(systems)
    latency = asyncio.run(run_latency())
    elapsed = time.time() - start

    md = to_markdown(results, latency)
    print(md)
    print("Total benchmark time: %.1fs (seed=%d, offline, no LLM)." % (elapsed, SEED))

    payload = {
        "disclaimer": DISCLAIMER,
        "seed": SEED,
        "max_facts": MAX_FACTS,
        "elapsed_s": round(elapsed, 2),
        "results": results,
        "latency_ms": latency,
    }
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print("JSON written to %s" % args.json)


if __name__ == "__main__":
    main()
