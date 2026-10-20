"""
Tests for hybrid embedding retrieval in MemoryVault with embedding_min_score.

Uses a fake embedder returning fixed vectors so cosine scores are exact.
"""
import asyncio
import math

import pytest

from cyrrus.memory import MemoryVault

numpy = pytest.importorskip("numpy", reason="numpy required for embedding tests")

numpy = pytest.importorskip("numpy", reason="numpy required for embedding tests")


def _unit_vector(cosine: float) -> list:
    """2D unit vector whose first component is `cosine`."""
    return [cosine, math.sqrt(max(0.0, 1.0 - cosine ** 2))]


class FakeEmbedder:
    """Deterministic fake embedder: vectors dict maps exact text -> vector."""
    def __init__(self, vectors):
        self.vectors = vectors

    def embed(self, texts):
        return [self.vectors.get(t, [0.0, 0.0]) for t in texts]


@pytest.mark.asyncio
async def test_keyword_match_low_embedding_score_still_returned(tmp_path):
    """(a) keyword/alias match with a LOW embedding score is still returned."""
    db_path = str(tmp_path / "hybrid_a.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "user name: Alice": _unit_vector(0.1),   # low embedding score
            "what is my name": [1.0, 0.0],            # query vector
        }),
        embedding_min_score=0.68,
    )
    await memory.upsert("s1", "user_name", "Alice", 2)
    slides = await memory.retrieve("s1", "what is my name", limit=3)
    ids = {s.id for s in slides}
    assert "mem_user_name" in ids, f"keyword match should be returned despite low embedding score, got {ids}"


@pytest.mark.asyncio
async def test_unrelated_query_below_threshold_returns_nothing(tmp_path):
    """(b) unrelated query with embedding score 0.64 returns nothing."""
    db_path = str(tmp_path / "hybrid_b.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "xyz place: Lisbon": _unit_vector(0.64),   # below 0.68 threshold
            "unrelated query about nothing": [1.0, 0.0],
        }),
        embedding_min_score=0.68,
    )
    await memory.upsert("s1", "xyz_place", "Lisbon", 2)
    slides = await memory.retrieve("s1", "unrelated query about nothing", limit=3)
    assert slides == [], f"expected no results below threshold, got {slides}"


@pytest.mark.asyncio
async def test_embedding_only_match_above_threshold_returned(tmp_path):
    """(c) embedding-only match scoring 0.75 with no keyword overlap is returned."""
    db_path = str(tmp_path / "hybrid_c.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "xyz place: Lisbon": _unit_vector(0.75),   # above 0.68 threshold
            "tell me about the weather": [1.0, 0.0],
        }),
        embedding_min_score=0.68,
    )
    await memory.upsert("s1", "xyz_place", "Lisbon", 2)
    slides = await memory.retrieve("s1", "tell me about the weather", limit=3)
    ids = {s.id for s in slides}
    assert "mem_xyz_place" in ids, f"embedding-only match should be returned, got {ids}"


@pytest.mark.asyncio
async def test_lowering_min_score_admits_lower_case(tmp_path):
    """(d) lowering embedding_min_score to 0.5 admits the 0.64 case."""
    db_path = str(tmp_path / "hybrid_d.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "xyz place: Lisbon": _unit_vector(0.64),
            "unrelated query about nothing": [1.0, 0.0],
        }),
        embedding_min_score=0.5,
    )
    await memory.upsert("s1", "xyz_place", "Lisbon", 2)
    slides = await memory.retrieve("s1", "unrelated query about nothing", limit=3)
    ids = {s.id for s in slides}
    assert "mem_xyz_place" in ids, f"with min_score=0.5, 0.64 should be admitted, got {ids}"


@pytest.mark.asyncio
async def test_no_embedder_behaviour_unchanged(tmp_path):
    """(e) with no embedder, behaviour is unchanged (keyword only)."""
    db_path = str(tmp_path / "hybrid_e.db")
    memory = MemoryVault(db_path=db_path)  # no embedder
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "user_city", "Lisbon", 2)
    slides = await memory.retrieve("s1", "what is my name", limit=3)
    ids = {s.id for s in slides}
    assert "mem_user_name" in ids
    assert "mem_user_city" not in ids


@pytest.mark.asyncio
async def test_hybrid_combines_keyword_and_embedding(tmp_path):
    """Keyword matches come first, then embedding-only matches, de-duped and capped."""
    db_path = str(tmp_path / "hybrid_combined.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "user name: Alice": _unit_vector(0.1),      # keyword match, low embedding
            "xyz place: Lisbon": _unit_vector(0.75),     # embedding-only match
            "xyz job: teacher": _unit_vector(0.9),       # embedding-only match
            "what is my name": [1.0, 0.0],
        }),
        embedding_min_score=0.68,
    )
    await memory.upsert("s1", "user_name", "Alice", 2)
    await memory.upsert("s1", "xyz_place", "Lisbon", 2)
    await memory.upsert("s1", "xyz_job", "teacher", 2)
    slides = await memory.retrieve("s1", "what is my name", limit=3)
    ids = [s.id for s in slides]
    # keyword match first
    assert ids[0] == "mem_user_name", f"keyword match should be first, got {ids}"
    # embedding-only matches follow
    assert "mem_xyz_place" in ids
    assert "mem_xyz_job" in ids


@pytest.mark.asyncio
async def test_below_threshold_tracked_in_trace(tmp_path):
    """Facts failing both keyword and embedding are reported as 'below threshold'."""
    db_path = str(tmp_path / "hybrid_trace.db")
    memory = MemoryVault(
        db_path=db_path,
        embedder=FakeEmbedder({
            "xyz place: Lisbon": _unit_vector(0.64),   # below threshold
            "unrelated query": [1.0, 0.0],
        }),
        embedding_min_score=0.68,
    )
    await memory.upsert("s1", "xyz_place", "Lisbon", 2)
    await memory.retrieve("s1", "unrelated query", limit=3)
    dropped = memory._last_retrieve_dropped_below_threshold
    assert any(d["key"] == "xyz_place" and d["reason"] == "below threshold" for d in dropped)