from __future__ import annotations
import asyncio
import logging
import os
import re
from typing import Optional, List, Dict, Any, Iterable
from .data import Slide
from .backend import MemoryBackend, validate_session_id, validate_keyword
from .sqlite_backend import SQLiteBackend, default_db_path
from .bm25 import bm25_rank_facts
from .trace import Trace

log = logging.getLogger("cyrrus.memory")


class MemoryVault:
    """
    Stores facts per session and retrieves the ones most relevant to
    whatever the user just said.

    Retrieval has two modes:
    - Keyword (default): BM25 word overlap scoring.
    - Semantic (opt-in): pass embedder= or embedding_model= to use fastembed.
      When an embedder is active, retrieval is hybrid: keyword/alias matches
      (BM25) are returned first in ranking order, then embedding-only matches
      with cosine score >= embedding_min_score are added, de-duplicated by
      fact id and capped at the limit.

    Pass an embedder to use semantic retrieval without loading a second model:

        bot = Projector(config, llm_call=my_llm,
                        memory=MemoryVault(embedder=my_router.model))

    embedding_min_score defaults to 0.68, calibrated for
    BAAI/bge-small-en-v1.5 on a small measurement. Lower it to admit more
    facts; raise it to be stricter.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        max_facts_per_session: Optional[int] = None,
        max_fact_value_length: int = 2000,
        embedder: object = None,
        embedding_model: Optional[str] = None,
        embedding_min_score: float = 0.68,
        backend: Optional[MemoryBackend] = None,
        trace_values: bool = False,
        min_relative_score: float = 0.5,
        pinned_keys: Optional[Iterable[str]] = None,
    ):
        self.max_facts_per_session = max_facts_per_session
        self.max_fact_value_length = max_fact_value_length
        self._embedder = embedder
        self._np = None
        self._embedding_min_score = embedding_min_score
        self.trace_values = trace_values
        self.min_relative_score = float(min_relative_score)
        self.pinned_keys = set(pinned_keys or ())
        self.last_retrieval_trace: Optional[Trace] = None

        # Embeddings are opt-in only.  Default retrieval is keyword (BM25).
        # Only load an embedding model if the caller explicitly passes
        # embedder= or embedding_model=.
        if embedder is not None:
            self._try_load_numpy()
        elif embedding_model is not None:
            self._try_load_embedder(embedding_model)

        # Use provided backend or default to SQLite (singleton per DB path)
        if db_path is None:
            db_path = default_db_path()
        if backend is not None:
            self._backend = backend
        else:
            from .sqlite_backend import get_backend
            self._backend = get_backend(db_path)
        
        # Initialize the backend (synchronous for SQLite, wrapped in backend if needed)
        # We'll lazy-initialize on first operation to avoid async issues in __init__
        self._initialized = False

    def _try_load_numpy(self):
        try:
            import numpy as np
            self._np = np
        except ImportError:
            log.warning("numpy not available — falling back to keyword retrieval.")
            self._embedder = None

    def _try_load_embedder(self, model_name: str):
        try:
            from fastembed import TextEmbedding
            import numpy as np
            self._embedder = TextEmbedding(model_name=model_name)
            self._np = np
            log.info("MemoryVault: semantic retrieval enabled (%s).", model_name)
        except ImportError:
            log.info("fastembed not installed — using keyword retrieval. "
                     "Install with: pip install cyrrus[embeddings]")
        except Exception as e:
            log.warning("Embedding model failed to load (%s) — using keyword retrieval.", e)

    async def _ensure_initialized(self):
        """Ensure the backend is initialized before operations."""
        if not self._initialized:
            try:
                await self._backend.init_db()
                self._initialized = True
            except Exception as e:
                log.warning("Backend initialization failed: %s", e)
                raise

    async def upsert(self, session_id: str, keyword: str, value: str, tokens: int):
        validate_session_id(session_id)
        validate_keyword(keyword)
        await self._ensure_initialized()
        await self._backend.upsert(
            session_id, keyword, value, tokens,
            self.max_facts_per_session,
            self.max_fact_value_length
        )

    async def retrieve(
        self,
        session_id: str,
        user_input: str,
        limit: int = 3,
        trace: Optional[Trace] = None,
        pinned_keys: Optional[Iterable[str]] = None,
    ) -> list:
        # Legacy contract (tests/test_failsafe.py::test_isolation): reading with a
        # falsy session id returns no facts instead of raising. Writes stay strict.
        if session_id is None or (isinstance(session_id, str) and not session_id.strip()):
            return []
        validate_session_id(session_id)
        trace_obj = trace if trace is not None else Trace(
            session_id=session_id, include_values=self.trace_values
        )
        trace_obj.session_id = session_id
        await self._ensure_initialized()

        if self._embedder is not None and self._np is not None:
            # Semantic path needs every active fact for the embedding pass.
            rows = await self._backend.retrieve_current(session_id, limit=None)
            if not rows:
                self.last_retrieval_trace = trace_obj
                return []
            slides = await self._semantic_retrieve(
                rows, user_input, limit, trace=trace_obj
            )
        else:
            # Keyword path: rank via the backend (per-session inverted index
            # in SQLiteBackend). Rankings are identical to bm25_rank_facts
            # over ALL active facts (limit=None), but without re-scanning
            # and re-ranking the whole corpus on every call.
            pins = set(self.pinned_keys)
            if pinned_keys:
                pins.update(pinned_keys)
            fetch_limit = limit + len(pins)
            try:
                ranked, dropped, explained = await self._backend.retrieve_ranked(
                    session_id,
                    user_input,
                    limit=fetch_limit,
                    score_threshold=0.0,
                    explain=True,
                )
            except TypeError:
                # Backend predates the explain kwarg.  Rank normally and
                # synthesize the bounded candidate list from its result.
                ranked, dropped = await self._backend.retrieve_ranked(
                    session_id,
                    user_input,
                    limit=fetch_limit,
                    score_threshold=0.0,
                )
                explained = []
                for pos, (score, kw, val, tok) in enumerate(ranked):
                    explained.append(
                        (score, kw, val, tok, True, None)
                        if pos < limit
                        else (score, kw, val, tok, False, "below_limit")
                    )
            self._last_retrieve_dropped_below_threshold = list(dropped)
            top_score = ranked[0][0] if ranked else 0.0
            floor = (
                top_score * self.min_relative_score if top_score > 0 else None
            )
            kept = []
            floor_dropped = []
            for pos, row in enumerate(ranked):
                score, kw, _val, _tok = row
                if pos == 0 or (floor is not None and score >= floor) or kw in pins:
                    kept.append(row)
                else:
                    floor_dropped.append(
                        {"key": kw, "reason": "below_relative_floor"}
                    )
            self._last_retrieve_dropped_below_threshold.extend(floor_dropped)
            kept_keys = {row[1] for row in kept}
            for score, kw, val, tok, included, drop_reason in explained:
                if included and kw not in kept_keys:
                    included = False
                    drop_reason = "below_relative_floor"
                elif not included and floor is not None and score < floor:
                    drop_reason = "below_relative_floor"
                elif included and kw in pins and score < (floor or 0):
                    drop_reason = None
                trace_obj.add_fact(
                    kw,
                    score,
                    val,
                    included,
                    reason=(
                        "pinned"
                        if included and kw in pins and score < (floor or 0)
                        else ("included" if included else None)
                    ),
                    dropped_reason=drop_reason,
                )
            slides = [
                Slide(
                    id=f"mem_{kw}",
                    type="memory",
                    content=f"Fact: {val}",
                    tokens=tok,
                    priority=800,
                )
                for _, kw, val, tok in kept
            ]

        self.last_retrieval_trace = trace_obj
        if slides:
            touched = [s.id.replace("mem_", "") for s in slides]
            await self._backend.touch(session_id, touched)

        return slides

    async def _semantic_retrieve(
        self, rows: list, user_input: str, limit: int, trace: Optional[Trace] = None
    ) -> list:
        try:
            # --- Pass 1: keyword/alias (BM25) matches first ---
            keyword_ranked = bm25_rank_facts(rows, user_input, limit=limit, score_threshold=0.0)
            keyword_kws = {kw for _, kw, _, _ in keyword_ranked}

            keyword_slides = []
            for score, kw, val, tok in keyword_ranked:
                if trace is not None:
                    trace.add_fact(
                        kw, score, val, True, reason="included"
                    )
                keyword_slides.append(Slide(
                    id=f"mem_{kw}",
                    type="memory",
                    content=f"Fact: {val}",
                    tokens=tok,
                    priority=800,
                ))

            # --- Pass 2: embedding-only matches for non-keyword facts ---
            remaining_rows = [r for r in rows if r[0] not in keyword_kws]
            embedding_slides = []
            dropped = []

            if remaining_rows:
                fact_texts = [
                    f"{kw.replace('_', ' ')}: {val}" if val else kw.replace("_", " ")
                    for kw, val, _ in remaining_rows
                ]

                query_emb = self._np.array(
                    list(self._embedder.embed([user_input]))[0]
                )
                fact_embs = self._np.array(list(self._embedder.embed(fact_texts)))

                norms = (
                    self._np.linalg.norm(fact_embs, axis=1)
                    * self._np.linalg.norm(query_emb)
                )
                norms[norms == 0] = 1e-9
                scores = fact_embs.dot(query_emb) / norms

                for idx, score in enumerate(scores):
                    kw, val, tok = remaining_rows[idx]
                    if score >= self._embedding_min_score:
                        if trace is not None:
                            trace.add_fact(
                                kw, float(score), val, True, reason="included"
                            )
                        embedding_slides.append(Slide(
                            id=f"mem_{kw}",
                            type="memory",
                            content=f"Fact: {val}",
                            tokens=tok,
                            priority=800,
                        ))
                    else:
                        if trace is not None:
                            trace.add_fact(
                                kw,
                                float(score),
                                val,
                                False,
                                dropped_reason="below_threshold",
                            )
                        dropped.append({"key": kw, "reason": "below threshold"})

            # Combine: keyword matches first, then embedding matches.
            # De-duplicate by fact id and cap at the limit.
            all_slides = keyword_slides + embedding_slides
            seen_ids = set()
            final_slides = []
            for s in all_slides:
                if s.id not in seen_ids:
                    seen_ids.add(s.id)
                    final_slides.append(s)
                if len(final_slides) >= limit:
                    break

            self._last_retrieve_dropped_below_threshold = dropped
            return final_slides

        except Exception as e:
            log.warning("Semantic retrieval failed (%s) — falling back to keywords.", e)
            return self._keyword_retrieve(rows, user_input, limit)

    def _keyword_retrieve(self, rows: list, user_input: str, limit: int) -> list:
        ranked = bm25_rank_facts(rows, user_input, limit=limit, score_threshold=0.0)
        included_kws = {kw for _, kw, _, _ in ranked}
        
        # Track dropped facts (below threshold - score <= 0)
        self._last_retrieve_dropped_below_threshold = []
        for kw, val, tok in rows:
            if kw not in included_kws:
                self._last_retrieve_dropped_below_threshold.append({"key": kw, "reason": "below threshold"})
        
        return [
            Slide(
                id=f"mem_{kw}",
                type="memory",
                content=f"Fact: {val}",
                tokens=tok,
                priority=800,
            )
            for _, kw, val, tok in ranked
        ]


    async def delete_session(self, session_id: str) -> int:
        """
        Delete all facts for a given session. Useful for GDPR compliance
        (right to be forgotten) and session cleanup.

        Returns the number of facts deleted.
        """
        validate_session_id(session_id)
        await self._ensure_initialized()
        return await self._backend.delete_session(session_id)

    async def get_fact_history(self, session_id: str, keyword: str) -> list:
        """
        Retrieve the full timeline of a fact for a given (session_id, keyword) pair.
        Returns all versions ordered by valid_at, including both current and superseded facts.
        
        Returns a list of dicts with keys: value, tokens, valid_at, invalid_at
        """
        validate_session_id(session_id)
        validate_keyword(keyword)
        await self._ensure_initialized()
        return await self._backend.get_fact_history(session_id, keyword)

    async def forget_fact(self, session_id: str, key: str) -> bool:
        """
        Physically delete ALL rows for (session_id, key), including
        superseded versions.

        Returns True if at least one row was deleted.
        """
        validate_session_id(session_id)
        validate_keyword(key)
        await self._ensure_initialized()
        return await self._backend.forget_fact(session_id, key)

    async def forget_session(self, session_id: str) -> int:
        """
        Delete all facts for a session.

        Returns the number of facts deleted.
        """
        validate_session_id(session_id)
        await self._ensure_initialized()
        return await self._backend.forget_session(session_id)

    async def export_facts(
        self, session_id: str, include_superseded: bool = False
    ) -> list[dict]:
        """
        Export facts for a session as JSON-serializable dicts.

        Args:
            session_id: The session identifier
            include_superseded: If True, include superseded versions.

        Returns:
            List of dicts with keys: key, value, created, invalid_at.
            Ordered by creation.
        """
        validate_session_id(session_id)
        await self._ensure_initialized()
        return await self._backend.export_facts(session_id, include_superseded)

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all sessions with their active fact counts.

        Returns:
            List of dicts with session information.
        """
        await self._ensure_initialized()
        return await self._backend.list_sessions()
