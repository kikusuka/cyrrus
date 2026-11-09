import sqlite3
import statistics
import time

import pytest

from cyrrus.bm25 import _select_query_terms
from cyrrus.bm25_index import SessionFactIndex
from cyrrus.config import validate_config
from cyrrus.memory import MemoryVault


def _facts(n):
    facts = []
    for i in range(n):
        facts.append(("note_%05d" % i,
                      "unrelated filler record %d about weather" % i, 6))
    return facts


def test_high_df_term_is_ignored_unless_it_removes_everything():
    facts = _facts(1)  # placeholder replaced below
    facts = [
        ("noise", "common " * 12, 12),
        ("target", "needle", 1),
    ]
    for i in range(8):
        facts.append(("filler_%d" % i, "common filler %d" % i, 3))
    index = SessionFactIndex(facts)
    ranked, _dropped, _explain, meta = index.rank(
        "common needle", limit=1, explain=True, with_terms=True,
        max_df_fraction=0.5,
    )
    assert ranked[0][1] == "target", ranked
    assert "common" in meta["high_df_terms"]
    assert meta["matched_terms"] == ["needle"]

    old, _d2, _e2, old_meta = index.rank(
        "common needle", limit=2, explain=True, with_terms=True,
        max_df_fraction=1.0, remove_stopwords=False,
    )
    # The old path still scores "common": the noise fact rides its term
    # frequency into second place even though it does not contain "needle".
    assert [r[1] for r in old] == ["target", "noise"], old
    assert old_meta["high_df_terms"] == []


def test_all_terms_high_df_falls_back_to_current_behavior():
    facts = [("f_%d" % i, "common filler %d" % i, 3) for i in range(6)]
    index = SessionFactIndex(facts)
    ranked, _dropped, _explain, meta = index.rank(
        "common", limit=3, explain=True, with_terms=True,
        max_df_fraction=0.5,
    )
    assert len(ranked) == 3
    assert meta["fallback_all_terms"] is True
    assert meta["selected_terms"] == ["common"]


def test_stopwords_are_reported_and_do_not_match():
    facts = [("the_key", "the a of i value", 5), ("target", "needle", 1)]
    for i in range(8):
        facts.append(("filler_%d" % i, "unrelated weather note %d" % i, 4))
    index = SessionFactIndex(facts)
    ranked, _dropped, _explain, meta = index.rank(
        "the a of I needle", limit=2, explain=True, with_terms=True,
        max_df_fraction=0.5,
    )
    assert [r[1] for r in ranked] == ["target"]
    assert set(meta["stopword_terms"]) == {"the", "a", "of", "i"}
    assert meta["matched_terms"] == ["needle"]
    assert meta["fallback_all_terms"] is False


def test_config_accepts_max_df_fraction():
    cfg = validate_config({"memory": {"max_df_fraction": 0.4}})
    assert cfg["memory"]["max_df_fraction"] == 0.4
    with pytest.raises(ValueError):
        validate_config({"memory": {"max_df_fraction": -0.1}})


async def _seed_topic_switch(vault):
    rows = [
        ("user_trip", "plan a trip to Rome in May"),
        ("user_hotel", "book a hotel near the Colosseum"),
        ("user_dinner", "plan a dinner party on Saturday"),
        ("user_recipe", "cook a lasagna for the party"),
    ]
    for kw, val in rows:
        await vault.upsert("s", kw, val, len(val.split()))


@pytest.mark.asyncio
async def test_topic_switch_stale_leak_before_and_after_term_weighting(tmp_path):
    before = MemoryVault(
        db_path=str(tmp_path / "topic_before.db"),
        min_relative_score=0.0,
        max_df_fraction=1.0,
    )
    await _seed_topic_switch(before)
    old_ranked = await before._backend.retrieve_ranked(
        "s", "help me plan the dinner", limit=5, score_threshold=0.0,
        max_df_fraction=1.0, remove_stopwords=False,
    )
    stale_before = sum(
        1 for _s, kw, _v, _t in old_ranked[0]
        if kw in ("user_trip", "user_hotel")
    )

    after = MemoryVault(
        db_path=str(tmp_path / "topic_after.db"),
        min_relative_score=0.0,
        max_df_fraction=0.5,
    )
    await _seed_topic_switch(after)
    new_ranked = await after._backend.retrieve_ranked(
        "s", "help me plan the dinner", limit=5, score_threshold=0.0,
        max_df_fraction=0.5, remove_stopwords=True, with_terms=True,
    )
    stale_after = sum(
        1 for _s, kw, _v, _t in new_ranked[0]
        if kw in ("user_trip", "user_hotel")
    )
    meta = new_ranked[2]
    assert stale_before == 2
    assert stale_after == 0
    assert "plan" in meta["high_df_terms"]
    assert meta["matched_terms"] == ["dinner"]


def _bulk_vault(db_path, n):
    vault = MemoryVault(db_path=str(db_path))
    import asyncio
    asyncio.run(vault.upsert("s", "user_location", "Lisbon", 1))
    base = time.time()
    rows = [
        ("s", "note_%06d" % i,
         "unrelated filler record %d about weather" % i, 6,
         base + i * 0.001, "2026-01-01T00:00:00", None)
        for i in range(n - 1)
    ]
    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        "INSERT INTO facts (session_id, keyword, value, tokens, "
        "last_accessed, valid_at, invalid_at) VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return vault


def _median_p95(vault, kwargs, calls=5):
    import asyncio
    samples = []
    for _ in range(calls):
        start = time.perf_counter()
        asyncio.run(vault.retrieve(
            "s", "note record location", limit=5, **kwargs
        ))
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
    return statistics.median(samples), p95


def test_worst_case_50k_query_median_p95_before_after(tmp_path):
    vault = _bulk_vault(tmp_path / "worst50k.db", 50000)
    old_vault = MemoryVault(
        db_path=str(tmp_path / "worst50k.db"), max_df_fraction=1.0
    )
    old_vault._initialized = True
    old_vault._backend = vault._backend
    old_vault.max_df_fraction = 1.0
    before_median, before_p95 = _median_p95(
        old_vault, {"max_df_fraction": 1.0}
    )
    after_median, after_p95 = _median_p95(
        vault, {"max_df_fraction": 0.5}
    )
    print(
        "50k worst-case median/p95 before=%.1f/%.1f ms after=%.1f/%.1f ms"
        % (before_median, before_p95, after_median, after_p95)
    )
    assert after_median < before_median


def test_pruning_fallback_keeps_stopwords_removed():
    # "who owns the project": df-pruning drops "project" (df=3 of 3), the
    # surviving "owns" matches nothing (df=0). The fallback must undo the
    # df-pruning but KEEP stopword removal — restoring "who"/"the" lets
    # project_name's "who am i" alias outrank the true project_owner, and the
    # relative floor then drops project_owner.
    df = {"who": 1, "owns": 0, "the": 3, "project": 3}
    sel, stop, high, fb = _select_query_terms(
        ["who", "owns", "the", "project"], df, 3,
        max_df_fraction=0.5, remove_stopwords=True,
    )
    assert fb is True
    assert high == ["project"]
    assert set(stop) == {"who", "the"}
    assert sel == ["owns", "project"], sel


@pytest.mark.asyncio
async def test_pruning_fallback_who_owns_the_project(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "owns.db"))
    await vault.upsert("s", "project_name", "the Atlas project", 8)
    await vault.upsert("s", "project_deadline", "the project is due friday", 8)
    await vault.upsert("s", "project_owner", "the project owner is Sam", 8)
    slides = await vault.retrieve("s", "who owns the project", limit=5)
    got = [s.id[4:] for s in slides]
    assert "project_owner" in got, got


@pytest.mark.asyncio
async def test_pruning_fallback_does_not_inflate_city_lookalikes(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "city.db"))
    await vault.upsert("s", "user_city", "Lisbon", 8)
    await vault.upsert("s", "friend_city", "my friend lives in a city called Madrid", 8)
    await vault.upsert("s", "cousin_city", "my cousin lives in a city called Paris", 8)
    await vault.upsert("s", "user_city", "Porto", 8)
    slides = await vault.retrieve("s", "which city do I live in", limit=5)
    got = [s.id[4:] for s in slides]
    assert "user_city" in got, got
