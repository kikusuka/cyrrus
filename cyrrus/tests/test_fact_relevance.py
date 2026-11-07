"""
STEP 2 regression tests: a relevant old fact must stay reachable no matter how
many newer/unrelated facts are stored after it.

Retrieval used to fetch only the 100 most-recently-accessed active facts
(MemoryVault.retrieve -> backend.retrieve_current(limit=100), ordered by
last_accessed DESC) and then BM25-rank just those. A fact buried under >100
newer rows never reached the ranker, so querying its topic returned nothing --
insertion order, not relevance, decided reachability. These tests fail on the
old behavior and pass once retrieval BM25-ranks *all* active facts.
"""
import time

import pytest

from cyrrus.memory import MemoryVault


async def _fill(vault, session, target_kw, target_val, n_distractors):
    await vault.upsert(session, target_kw, target_val, len(target_val.split()))
    for i in range(n_distractors):
        kw = "note_%05d" % i
        val = "unrelated filler record number %d about the weather" % i
        await vault.upsert(session, kw, val, len(val.split()))


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
async def test_buried_fact_reachable_and_fast(tmp_path, n):
    vault = MemoryVault(db_path=str(tmp_path / ("r%d.db" % n)))
    session = "s1"
    await _fill(vault, session, "user_location", "Lisbon", n)

    start = time.perf_counter()
    slides = await vault.retrieve(session, "where do I live?", limit=5)
    elapsed = time.perf_counter() - start

    keys = [s.id for s in slides]
    assert "mem_user_location" in keys, "buried fact unreachable at n=%d" % n
    # Retrieval (BM25 over all active facts) must stay well under a second.
    assert elapsed < 1.0, "retrieval too slow at n=%d: %.3fs" % (n, elapsed)
