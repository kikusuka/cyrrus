"""
Tests for BM25-based retrieval in MemoryVault (Part C).

Covers:
- BM25Ranker basic scoring correctness
- bm25_rank_facts helper correctness
- MemoryVault BM25 retrieval ranks correctly with 100+ facts
- Session isolation still works with BM25
- Temporal memory (valid_at/invalid_at) still works with BM25
- Backward compatibility with simple keyword queries
"""
import pytest
import asyncio
from typing import List, Tuple

from cyrrus.bm25 import BM25Ranker, bm25_rank_facts
from cyrrus.memory import MemoryVault


class TestBM25Ranker:
    """Direct tests for the BM25Ranker class."""

    def test_empty_corpus(self):
        ranker = BM25Ranker([])
        assert ranker.corpus_size == 0
        assert ranker.score_query("anything") == []
        idx, scores = ranker.top_k("anything", k=3)
        assert idx == []
        assert scores == []

    def test_single_document(self):
        ranker = BM25Ranker(["hello world python code"])
        assert ranker.corpus_size == 1
        idx, scores = ranker.top_k("python", k=3)
        assert idx == [0]
        assert len(scores) == 1
        assert scores[0] > 0

    def test_ranking_distinct_topics(self):
        docs = [
            "Python programming language tutorial syntax",
            "Machine learning neural network deep model",
            "Weather forecast temperature rain tomorrow",
            "Cooking Italian pasta tomato sauce recipe",
        ]
        ranker = BM25Ranker(docs)

        idx_py, _ = ranker.top_k("python programming tutorial", k=2)
        assert idx_py[0] == 0

        idx_ml, _ = ranker.top_k("neural network deep learning", k=2)
        assert idx_ml[0] == 1

        idx_wx, _ = ranker.top_k("tomorrow rain temperature", k=2)
        assert idx_wx[0] == 2

        idx_ck, _ = ranker.top_k("Italian pasta sauce", k=2)
        assert idx_ck[0] == 3

    def test_score_query_returns_same_length(self):
        docs = ["a", "b c", "d e f"]
        ranker = BM25Ranker(docs)
        scores = ranker.score_query("query")
        assert len(scores) == len(docs)
        for s in scores:
            assert isinstance(s, float)

    def test_top_k_respects_k(self):
        docs = ["query"] * 10
        ranker = BM25Ranker(docs)
        idx, scores = ranker.top_k("query", k=3)
        assert len(idx) <= 3
        assert len(scores) <= 3


class TestBm25RankFacts:
    """Tests for the bm25_rank_facts helper."""

    def test_empty_facts(self):
        result = bm25_rank_facts([], "anything")
        assert result == []

    def test_basic_ranking(self):
        facts = [
            ("proj", "Python LLM library cyrrus", 3),
            ("food", "Italian tomato pasta sauce", 3),
            ("wx", "weather forecast rain", 3),
        ]
        ranked = bm25_rank_facts(facts, "Python LLM project", limit=3)
        # First result should be proj
        assert ranked[0][1] == "proj"
        # Each returned tuple: (score, kw, val, tok)
        for score, kw, val, tok in ranked:
            assert isinstance(score, float)
            assert score > 0
            assert kw in ("proj", "food", "wx")
            assert isinstance(val, str)
            assert isinstance(tok, int)

    def test_limit_parameter(self):
        facts = [(f"k{i}", f"fact number {i} with words", 3) for i in range(10)]
        ranked = bm25_rank_facts(facts, "fact number", limit=3)
        assert len(ranked) <= 3


class TestMemoryVaultBM25:
    """BM25 integration tests through MemoryVault."""

    @pytest.mark.asyncio
    async def test_basic_retrieval_backward_compat(self):
        memory = MemoryVault(db_path=":memory:")
        try:
            await memory.upsert("s1", "name", "Alice Wonderland", 2)
            await memory.upsert("s1", "age", "thirty years old", 2)

            res = await memory.retrieve("s1", "what is my name", limit=3)
            assert len(res) >= 1
            assert "Alice" in res[0].content
        finally:
            await memory.delete_session("s1")

    @pytest.mark.asyncio
    async def test_session_isolation(self):
        memory = MemoryVault(db_path=":memory:")
        try:
            await memory.upsert("A", "x", "Python Django framework", 3)
            await memory.upsert("B", "x", "Italian pasta recipe", 3)

            resA = await memory.retrieve("A", "Python Django", limit=2)
            assert len(resA) >= 1
            assert "Django" in resA[0].content
            assert "pasta" not in resA[0].content.lower()

            resB = await memory.retrieve("B", "Italian pasta", limit=2)
            assert len(resB) >= 1
            assert "pasta" in resB[0].content
            assert "Django" not in resB[0].content
        finally:
            await memory.delete_session("A")
            await memory.delete_session("B")

    @pytest.mark.asyncio
    async def test_temporal_memory_only_current_scored(self):
        memory = MemoryVault(db_path=":memory:")
        try:
            await memory.upsert("s1", "user_name", "Alice old 2023 version", 4)
            await memory.upsert("s1", "user_name", "Bob current 2025", 3)

            res = await memory.retrieve("s1", "current user name", limit=5)
            assert len(res) >= 1
            top = res[0].content
            assert "Bob" in top
            assert "Alice" not in top

            history = await memory.get_fact_history("s1", "user_name")
            assert len(history) == 2
        finally:
            await memory.delete_session("s1")

    @pytest.mark.asyncio
    async def test_bm25_scales_over_100_facts(self):
        memory = MemoryVault(db_path=":memory:")
        try:
            fillers = [
                ("animal", "golden retriever dog puppy fur bark"),
                ("food", "pasta tomato basil sauce italian cuisine"),
                ("place", "Hawaii beach palm ocean wave resort"),
                ("hobby", "photography camera lens landscape nature"),
                ("music", "jazz piano saxophone rhythm blues chord"),
                ("book", "novel fiction fantasy character plot chapter"),
                ("car", "electric SUV battery range autonomous driving"),
                ("city", "Paris Eiffel croissant Louvre museum art"),
            ]
            for i in range(13):
                for kw, val in fillers:
                    await memory.upsert(
                        "s1",
                        f"{kw}_{i}",
                        f"{val} variation {i} extra noise words here",
                        7,
                    )

            # 3 target facts
            await memory.upsert("s1", "target_proj",
                "cyrrus Python LLM context routing library", 8)
            await memory.upsert("s1", "target_meeting",
                "project review meeting Tuesday 3pm deadline", 7)
            await memory.upsert("s1", "target_db",
                "PostgreSQL SQLite backend storage schema database", 8)

            res1 = await memory.retrieve(
                "s1", "Python LLM project context routing", limit=3)
            assert res1[0].id == "mem_target_proj"

            res2 = await memory.retrieve(
                "s1", "Tuesday deadline meeting review", limit=3)
            assert res2[0].id == "mem_target_meeting"

            res3 = await memory.retrieve(
                "s1", "PostgreSQL database storage backend schema", limit=3)
            assert res3[0].id == "mem_target_db"
        finally:
            await memory.delete_session("s1")

    @pytest.mark.asyncio
    async def test_bm25_ranks_higher_relevance_first(self):
        memory = MemoryVault(db_path=":memory:")
        try:
            # Less relevant
            await memory.upsert("s1", "misc_py",
                "Python snake animal reptile", 4)
            # More relevant: mentions both "python" and "project" and "library"
            await memory.upsert("s1", "main_py_project",
                "Python cyrrus project library code framework programming", 7)

            res = await memory.retrieve(
                "s1", "What is my cyrrus Python project library?", limit=3)
            # The richer match should be top
            assert res[0].id == "mem_main_py_project"
        finally:
            await memory.delete_session("s1")
