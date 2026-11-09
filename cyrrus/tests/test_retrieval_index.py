"""
Tests for the per-session inverted-index retrieval path (Item 3, phase 1b).

The SQLiteBackend must expose retrieve_ranked() that returns results
IDENTICAL to ranking all active facts with bm25_rank_facts, while avoiding
a full re-scan/re-rank of the corpus on every call.

DELIBERATE BEHAVIOR CHANGE (v8 item 3): both paths now drop query
stopwords and ignore terms present in at least ``max_df_fraction`` (0.5)
of a session's facts, with a fallback to the non-stopword terms when that
would remove all of them. The parity expectations below therefore pass
the same defaults to bm25_rank_facts; callers wanting the pre-v8 ranking
can pass ``max_df_fraction=1.0, remove_stopwords=False``.
"""
import asyncio
import random
import time

import pytest

from cyrrus.bm25 import bm25_rank_facts
from cyrrus.sqlite_backend import SQLiteBackend


WORDS = [
    "python", "guitar", "lisbon", "porto", "coffee", "tea", "jazz", "rock",
    "dog", "cat", "paris", "berlin", "tokyo", "server", "database", "cache",
    "morning", "evening", "pizza", "sushi", "hiking", "cycling", "reading",
    "writing", "machine", "learning", "neural", "network", "graph", "tree",
]


def _random_facts(n: int, seed: int):
    rng = random.Random(seed)
    facts = []
    for i in range(n):
        kw = "fact_%d_%s" % (i, rng.choice(WORDS))
        val = " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 12)))
        tok = len(val.split())
        facts.append((kw, val, tok))
    return facts


@pytest.fixture()
def backend(tmp_path):
    db = str(tmp_path / "index_test.db")
    b = SQLiteBackend(db)
    yield b
    try:
        asyncio.run(b.close())
    except Exception:
        pass


async def _seed(backend, session_id, facts):
    await backend.init_db()
    for kw, val, tok in facts:
        await backend.upsert(session_id, kw, val, tok, 100000, 4096)


class TestRetrieveRankedParity:
    """retrieve_ranked() must produce identical rankings to bm25_rank_facts
    over all active facts (the phase 1 correctness behavior)."""

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
    async def test_identical_ranking_random_data(self, backend, seed):
        session = "sess_%d" % seed
        facts = _random_facts(120, seed)
        await _seed(backend, session, facts)

        queries = [
            "tell me about python and coffee",
            "where do i live lisbon or porto",
            "dog cat pet",
            "machine learning network",
            "completely unrelated xyzzy query",
            "pizza sushi tea morning",
        ]
        rows = await backend.retrieve_current(session, limit=None)
        for q in queries:
            for limit in (1, 3, 10):
                expected = bm25_rank_facts(rows, q, limit=limit,
                                           score_threshold=0.0)
                ranked, dropped = await backend.retrieve_ranked(
                    session, q, limit=limit, score_threshold=0.0)
                assert ranked == expected, (
                    "seed=%d limit=%d query=%r\nranked=%r\nexpected=%r"
                    % (seed, limit, q, ranked, expected))

    async def test_identical_ranking_after_writes(self, backend):
        """Index must stay correct across upserts (supersede) and deletes."""
        session = "writes"
        facts = _random_facts(60, 42)
        await _seed(backend, session, facts)

        # Supersede an existing fact and add new ones
        await backend.upsert(session, facts[0][0], "brand new value about sushi",
                             5, 100000, 4096)
        await backend.upsert(session, "extra_fact", "guitar jazz evening", 3,
                             100000, 4096)
        await backend.delete_session(session)
        await _seed(backend, session, _random_facts(40, 7))

        rows = await backend.retrieve_current(session, limit=None)
        q = "jazz guitar evening music"
        expected = bm25_rank_facts(rows, q, limit=5, score_threshold=0.0)
        ranked, _dropped = await backend.retrieve_ranked(session, q, limit=5)
        assert ranked == expected

    async def test_score_threshold(self, backend):
        session = "thresh"
        await _seed(backend, session, _random_facts(50, 9))
        rows = await backend.retrieve_current(session, limit=None)
        q = "python coffee"
        expected = bm25_rank_facts(rows, q, limit=5, score_threshold=2.0)
        ranked, _dropped = await backend.retrieve_ranked(
            session, q, limit=5, score_threshold=2.0)
        assert ranked == expected

    async def test_empty_session(self, backend):
        await backend.init_db()
        ranked, dropped = await backend.retrieve_ranked("nobody", "hello", limit=3)
        assert ranked == []
        assert dropped == []

    async def test_dropped_below_threshold_capped(self, backend):
        """Dropped list is capped so huge corpora don't allocate O(N) dicts."""
        session = "capped"
        await _seed(backend, session, _random_facts(250, 11))
        _ranked, dropped = await backend.retrieve_ranked(
            session, "zzz qqq nonexistent", limit=3)
        assert len(dropped) <= 100
        assert all(d["reason"] == "below threshold" for d in dropped)


class TestIndexCaching:
    """Repeated retrieves must not re-scan/re-rank the whole corpus."""

    async def test_repeated_retrieve_is_faster_than_first(self, backend):
        session = "perf"
        await _seed(backend, session, _random_facts(2000, 123))

        t0 = time.perf_counter()
        await backend.retrieve_ranked(session, "python coffee morning", limit=5)
        cold = time.perf_counter() - t0

        times = []
        for i in range(20):
            t = time.perf_counter()
            await backend.retrieve_ranked(session, "guitar jazz %d" % i, limit=5)
            times.append(time.perf_counter() - t)
        warm_median = sorted(times)[len(times) // 2]
        assert warm_median < cold, (
            "warm median %.4fs should beat cold %.4fs" % (warm_median, cold))

    async def test_writes_from_same_backend_are_seen(self, backend):
        session = "fresh"
        await _seed(backend, session, [("user_name", "Alice Smith", 2)])
        ranked, _ = await backend.retrieve_ranked(session, "what is my name", limit=3)
        assert any(kw == "user_name" for (_s, kw, _v, _t) in ranked)

        await backend.upsert(session, "user_name", "Bob Jones", 2, 100000, 4096)
        ranked, _ = await backend.retrieve_ranked(session, "what is my name", limit=3)
        assert any(val == "Bob Jones" for (_s, _kw, val, _t) in ranked)
