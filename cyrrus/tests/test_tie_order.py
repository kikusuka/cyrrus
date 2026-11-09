"""
Item 2 (phase 1c): deterministic tie order.

Ranking must be independent of touch()/recency: ties break by
(score desc, stable fact id asc) in BOTH bm25_rank_facts and the
SessionFactIndex. The fact id is the keyword, which is unique among a
session's active facts, so (score, keyword) is a total order.

This is a DELIBERATE BEHAVIOR CHANGE. Previously ties broke by document
index, i.e. the row order (last_accessed DESC). touch() reorders rows, so a
cached index (old row order) and a fresh bm25_rank_facts over
retrieve_current (new row order) could pick different facts at a tie
boundary, or return the same facts in a different order. After this change
both rankers are order-independent.

The parity test below fails pre-fix on tie-heavy data once touch() reorders
the rows, and passes once both rankers tie-break by fact id.

DELIBERATE BEHAVIOR CHANGE (v8 item 3): query stopwords and high-df terms
are now dropped by default in both rankers. The parity calls below rely on
both sides using the same term-weighting defaults; the score tiers in this
file are single-token queries that survive the fallback, so the tie groups
remain exact ties.
"""
import random

import pytest

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.sqlite_backend import SQLiteBackend

WORDS = [
    "python", "guitar", "lisbon", "porto", "coffee", "tea", "jazz", "rock",
    "dog", "cat", "paris", "berlin", "tokyo", "server", "database", "cache",
    "morning", "evening", "pizza", "sushi", "hiking", "cycling", "reading",
    "writing", "machine", "learning", "neural", "network", "graph", "tree",
]
# Tie groups draw from TIE_WORDS, unique facts from UNIQ_WORDS, so a
# group-word query matches ONLY that group and every fact in it scores
# identically (a guaranteed tie).
TIE_WORDS = WORDS[:15]
UNIQ_WORDS = WORDS[15:]


def _tie_facts(seed):
    rng = random.Random(seed)
    facts = []
    groups = []
    for g in range(rng.randint(2, 3)):
        words = [rng.choice(TIE_WORDS) for _ in range(3)]
        size = rng.randint(4, 6)
        gkws = []
        for i in range(size):
            kw = "tie%d_%d" % (g, i)
            val = " ".join(words)
            facts.append((kw, val, len(val.split())))
            gkws.append(kw)
        groups.append((words, gkws))
    for j in range(rng.randint(4, 8)):
        kw = "uniq%d" % j
        val = " ".join(rng.choice(UNIQ_WORDS) for _ in range(rng.randint(2, 6)))
        facts.append((kw, val, len(val.split())))
    return facts, groups, rng


def _queries(groups, facts, rng):
    qs = []
    for words, _gkws in groups:
        qs.append(" ".join(words))
        qs.append(words[0])
    while len(qs) < 10:
        _kw, val, _t = facts[rng.randrange(len(facts))]
        qs.append(" ".join(val.split()[:2]))
    return qs[:10]


async def _parity(backend, session, queries, limits):
    """Index ranking must equal a fresh bm25_rank_facts over the live rows."""
    rows = await backend.retrieve_current(session, limit=None)
    for q in queries:
        for limit in limits:
            ranked, _drop = await backend.retrieve_ranked(session, q, limit=limit)
            fresh = bm25_rank_facts(rows, q, limit=limit, score_threshold=0.0)
            assert ranked == fresh, (
                "parity broken q=%r limit=%d\nindex=%r\nfresh=%r"
                % (q, limit, ranked, fresh))


@pytest.mark.parametrize("seed", list(range(20)))
async def test_tie_order_parity(tmp_path, seed):
    db = str(tmp_path / ("tie_%d.db" % seed))
    backend = SQLiteBackend(db)
    limits = (3, 10, 50)
    try:
        await backend.init_db()
        facts, groups, rng = _tie_facts(seed)
        session = "s"
        for kw, val, tok in facts:
            await backend.upsert(session, kw, val, tok, 100000, 4096)
        queries = _queries(groups, facts, rng)

        # Build the index, then parity with no reordering (holds pre-fix too).
        await backend.retrieve_ranked(session, queries[0], limit=3)
        await _parity(backend, session, queries, limits)

        # Case B: touch reorders rows; the cached index keeps the old order.
        # Touching the second half of each group rotates its row order, so a
        # doc-index tie-break diverges from the fresh ranking. A fact-id
        # tie-break does not.
        for _words, gkws in groups:
            await backend.touch(session, gkws[len(gkws) // 2:])
        await _parity(backend, session, queries, limits)

        # Case C: supersede a tie-group fact, rebuild, touch, compare.
        g0words, g0kws = groups[0]
        await backend.upsert(session, g0kws[0], " ".join(g0words), 3, 100000, 4096)
        await backend.retrieve_ranked(session, queries[0], limit=3)
        await backend.touch(session, g0kws[len(g0kws) // 2:])
        await _parity(backend, session, queries, limits)

        # Case D: delete a fact, rebuild, touch, compare.
        await backend.forget_fact(session, g0kws[1])
        await backend.retrieve_ranked(session, queries[0], limit=3)
        await backend.touch(session, g0kws[len(g0kws) // 2:])
        await _parity(backend, session, queries, limits)
    finally:
        await backend.close()


def test_bm25_rank_facts_ties_break_by_keyword():
    """Direct unit check: equal scores order by keyword ascending."""
    facts = [
        ("zulu", "zeta zeta zeta", 3),
        ("alpha", "zeta zeta zeta", 3),
        ("mike", "zeta zeta zeta", 3),
    ]
    ranked = bm25_rank_facts(facts, "zeta", limit=3, score_threshold=0.0)
    scores = [s for s, _k, _v, _t in ranked]
    assert scores[0] == scores[1] == scores[2], "expected a three-way tie"
    assert [kw for _s, kw, _v, _t in ranked] == ["alpha", "mike", "zulu"]
