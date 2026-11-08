"""Hybrid keyword + embedding retrieval with reciprocal-rank fusion.

This is the built-in ``hybrid`` retriever plugin (select it with
``{"plugins": {"retriever": "hybrid"}}``). It intentionally keeps the BM25
side unchanged and adds an embedding side when an embedder is configured.

Fusion is reciprocal rank fusion (RRF):

    score(fact) = 1 / (k + bm25_rank) + 1 / (k + embedding_rank)

with rank starting at 1 and ``k`` configurable (default 60). RRF needs no
score calibration between BM25 and cosine. Ties break by fact keyword so the
result is deterministic.

Any embedding error or timeout falls back to the BM25 result and logs a
warning once per retriever instance, so a flaky endpoint cannot break memory
injection.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bm25 import bm25_rank_facts
from .embeddings import OpenAIEmbedder, SQLiteEmbeddingStore, cosine_similarity

log = logging.getLogger("cyrrus.hybrid")

Fact = Tuple[str, str, int]
RankedFact = Tuple[float, str, str, int]


def _fact_text(keyword: str, value: str) -> str:
    if value:
        return "%s: %s" % (keyword.replace("_", " "), value)
    return keyword.replace("_", " ")


class HybridRetriever:
    """RRF fusion of BM25 and cosine similarity over fact embeddings."""

    name = "hybrid"

    def __init__(
        self,
        embedder: Any = None,
        store: Optional[SQLiteEmbeddingStore] = None,
        db_path: Optional[str] = None,
        model: Optional[str] = None,
        rrf_k: int = 60,
        min_similarity: float = 0.0,
        max_df_fraction: float = 0.5,
        remove_stopwords: bool = True,
        session_id: Optional[str] = None,
    ):
        self.embedder = embedder
        self.model = model or getattr(embedder, "model", None) or "default"
        self.rrf_k = max(1, int(rrf_k))
        self.min_similarity = float(min_similarity)
        self.max_df_fraction = float(max_df_fraction)
        self.remove_stopwords = bool(remove_stopwords)
        self.session_id = session_id
        self.store = store
        if self.store is None and db_path:
            self.store = SQLiteEmbeddingStore(db_path)
        self.last_terms: Dict[str, Any] = {}
        self.last_fallback = False
        self._fallback_warned = False

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "HybridRetriever":
        """Build from the plugin config mapping.

        Recognised keys: ``embedder`` (an object with ``embed()``), ``db_path``,
        ``model``/``embedding_model``, ``base_url``/``embedding_base_url``,
        ``api_key``, ``api_key_env``, ``timeout``, ``batch_size``,
        ``dimensions``, ``rrf_k``, ``min_similarity``, ``max_df_fraction`` and
        ``remove_stopwords``.
        """
        config = dict(config or {})
        embedder = config.get("embedder")
        model = config.get("embedding_model") or config.get("model")
        if embedder is None:
            base_url = config.get("embedding_base_url") or config.get("base_url")
            if base_url and model:
                embedder = OpenAIEmbedder(
                    base_url=base_url,
                    model=model,
                    api_key=config.get("api_key"),
                    api_key_env=config.get("api_key_env"),
                    timeout=float(config.get("timeout", 10.0)),
                    batch_size=int(config.get("batch_size", 64)),
                    dimensions=config.get("dimensions"),
                )
        return cls(
            embedder=embedder,
            db_path=config.get("db_path"),
            model=model,
            rrf_k=int(config.get("rrf_k", 60)),
            min_similarity=float(config.get("min_similarity", 0.0)),
            max_df_fraction=float(config.get("max_df_fraction", 0.5)),
            remove_stopwords=bool(config.get("remove_stopwords", True)),
            session_id=config.get("session_id"),
        )

    def _warn_fallback(self, exc: BaseException) -> None:
        if not self._fallback_warned:
            self._fallback_warned = True
            log.warning(
                "Hybrid retrieval failed (%s); falling back to BM25 "
                "(this warning is logged once per retriever).",
                exc,
            )
        else:
            log.debug("Hybrid retrieval still failing (%s); BM25 fallback.", exc)

    def _embeddings(
        self,
        facts: Sequence[Fact],
        query: str,
        session_id: Optional[str],
    ) -> Tuple[Optional[List[float]], List[List[float]]]:
        """Return (query vector, fact vectors), using the SQLite cache."""
        if self.embedder is None:
            return None, []

        sid = session_id or self.session_id or "__anonymous__"
        cached: Dict[str, List[float]] = {}
        if self.store is not None:
            try:
                cached = self.store.get(sid, self.model, facts)
            except Exception as exc:  # cache is best-effort
                log.debug("Embedding cache read failed (%s); recomputing.", exc)
                cached = {}

        missing_positions = [
            index for index, (keyword, _value, _tokens) in enumerate(facts)
            if keyword not in cached
        ]
        if missing_positions:
            missing_facts = [facts[index] for index in missing_positions]
            missing_vectors = self.embedder.embed(
                [_fact_text(keyword, value) for keyword, value, _tokens in missing_facts]
            )
            if len(missing_vectors) != len(missing_facts):
                raise ValueError(
                    "embedder returned %d vectors for %d facts"
                    % (len(missing_vectors), len(missing_facts))
                )
            for (keyword, _value, _tokens), vector in zip(
                missing_facts, missing_vectors
            ):
                cached[keyword] = [float(x) for x in vector]
            if self.store is not None:
                try:
                    self.store.put(sid, self.model, missing_facts, missing_vectors)
                except Exception as exc:  # cache is best-effort
                    log.debug("Embedding cache write failed (%s).", exc)

        fact_vectors = [cached[keyword] for keyword, _value, _tokens in facts]
        query_vector = self.embedder.embed([query])[0]
        return [float(x) for x in query_vector], fact_vectors

    def rank(
        self,
        facts: Sequence[Fact],
        query: str,
        limit: int = 3,
        score_threshold: float = 0.0,
        session_id: Optional[str] = None,
        max_df_fraction: Optional[float] = None,
        remove_stopwords: Optional[bool] = None,
        **kwargs: Any,
    ) -> List[RankedFact]:
        facts = list(facts)
        self.last_fallback = False
        if not facts:
            self.last_terms = {}
            return []

        df_fraction = (
            self.max_df_fraction
            if max_df_fraction is None
            else float(max_df_fraction)
        )
        drop_stopwords = (
            self.remove_stopwords
            if remove_stopwords is None
            else bool(remove_stopwords)
        )
        bm25_rows, term_meta = bm25_rank_facts(
            facts,
            query,
            limit=max(1, len(facts)),
            score_threshold=0.0,
            max_df_fraction=df_fraction,
            remove_stopwords=drop_stopwords,
            return_terms=True,
        )
        self.last_terms = term_meta

        # No embedder: behave exactly like the BM25 retriever.
        if self.embedder is None:
            return [
                row for row in bm25_rows if row[0] > score_threshold
            ][:limit]

        try:
            query_vector, fact_vectors = self._embeddings(
                facts, query, session_id
            )
            if query_vector is None:
                return [
                    row for row in bm25_rows if row[0] > score_threshold
                ][:limit]
            similarities = []
            for index, vector in enumerate(fact_vectors):
                similarity = cosine_similarity(query_vector, vector)
                if math.isfinite(similarity) and similarity > self.min_similarity:
                    similarities.append((similarity, index))
        except Exception as exc:
            self._warn_fallback(exc)
            self.last_fallback = True
            return [
                row for row in bm25_rows if row[0] > score_threshold
            ][:limit]

        similarities.sort(key=lambda item: (-item[0], facts[item[1]][0]))
        embedding_rank = {
            facts[index][0]: position
            for position, (_similarity, index) in enumerate(similarities, start=1)
        }
        bm25_rank = {
            row[1]: position for position, row in enumerate(bm25_rows, start=1)
        }

        by_keyword = {
            keyword: (value, tokens) for keyword, value, tokens in facts
        }
        fused = []
        for keyword in set(bm25_rank) | set(embedding_rank):
            score = 0.0
            if keyword in bm25_rank:
                score += 1.0 / (self.rrf_k + bm25_rank[keyword])
            if keyword in embedding_rank:
                score += 1.0 / (self.rrf_k + embedding_rank[keyword])
            value, tokens = by_keyword[keyword]
            fused.append((score, keyword, value, tokens))

        fused.sort(key=lambda row: (-row[0], row[1]))
        return [
            row for row in fused if row[0] > score_threshold
        ][:limit]
