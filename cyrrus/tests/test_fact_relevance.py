"""
STEP 2 regression tests: a relevant old fact must stay reachable no matter how
many newer/unrelated facts are stored after it.

Retrieval used to fetch only the 100 most-recently-accessed active facts
(MemoryVault.retrieve -> backend.retrieve_current(limit=100), ordered by
last_accessed DESC) and then BM25-rank just those. A fact buried under >100
newer rows never reached the ranker, so querying its topic returned nothing --
insertion order, not relevance, decided reachability. These tests fail on the
old behavior and pass once retrieval BM25-ranks *all* active facts.

v8c item 3: the old wall-clock guard (elapsed < 1.0 s at n=5000) was a
machine-load artifact, not a correctness failure -- it measured once against an
absolute budget that varies with CPU contention and the one-time cold index
build. It is replaced by a RELATIVE bound: the 5000-fact retrieval time must
stay under 20x the 1000-fact time, taking the MEDIAN of 5 calls so the cold
build is washed out. This tests the warm retrieval *scaling*, independent of
machine speed.
"""
import statistics
import time

import pytest

from cyrrus.memory import MemoryVault


async def _fill(vault, session, target_kw, target_val, n_distractors):
    await vault.upsert(session, target_kw, target_val, len(target_val.split()))
    for i in range(n_distractors):
        kw = "note_%05d" % i
        val = "unrelated filler record number %d about the weather" % i
        await vault.upsert(session, kw, val, len(val.split()))


async def _median_seconds(vault, session, query, calls=5):
    samples = []
    for _ in range(calls):
        start = time.perf_counter()
        await vault.retrieve(session, query, limit=5)
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


@pytest.mark.asyncio
async def test_old_fact_reachable_after_150_newer(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "r150.db"))
    session = "s1"
    await _fill(vault, session, "user_location", "Lisbon", 150)
    slides = await vault.retrieve(session, "where do I live?", limit=5)
    keys = [s.id for s in slides]
    assert "mem_user_location" in keys


@pytest.mark.asyncio
@pytest.mark.parametrize("n", [150, 1000, 5000])
async def test_buried_fact_reachable(tmp_path, n):
    vault = MemoryVault(db_path=str(tmp_path / ("r%d.db" % n)))
    session = "s1"
    await _fill(vault, session, "user_location", "Lisbon", n)

    slides = await vault.retrieve(session, "where do I live?", limit=5)
    keys = [s.id for s in slides]
    assert "mem_user_location" in keys, "buried fact unreachable at n=%d" % n


@pytest.mark.asyncio
async def test_buried_fact_reachable_and_fast(tmp_path):
    # v8c item 3: relative scaling bound replaces the absolute <1.0s wall limit.
    small = MemoryVault(db_path=str(tmp_path / "r1000.db"))
    await _fill(small, "s1", "user_location", "Lisbon", 1000)
    big = MemoryVault(db_path=str(tmp_path / "r5000.db"))
    await _fill(big, "s1", "user_location", "Lisbon", 5000)

    # Median of 5 warm retrieves each; the cold per-session index build is the
    # slowest single call and drops out of the median.
    t_small = await _median_seconds(small, "s1", "where do I live?")
    t_big = await _median_seconds(big, "s1", "where do I live?")

    keys = [s.id for s in await big.retrieve("s1", "where do I live?", limit=5)]
    assert "mem_user_location" in keys, "buried fact unreachable at n=5000"

    assert t_big < 20.0 * t_small, (
        "5000-fact retrieval %.1f ms not < 20x the 1000-fact time %.1f ms"
        % (t_big * 1000.0, t_small * 1000.0)
    )
