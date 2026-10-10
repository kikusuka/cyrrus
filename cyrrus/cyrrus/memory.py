import asyncio
import logging
import os
import re
from typing import Optional
from .data import Slide
from .backend import MemoryBackend, validate_session_id, validate_keyword
from .sqlite_backend import SQLiteBackend
from .bm25 import bm25_rank_facts

log = logging.getLogger("cyrrus.memory")


class MemoryVault:
    """
    Stores facts per session and retrieves the ones most relevant to
    whatever the user just said.

    Retrieval has two modes:
    - Semantic (default when embeddings are available): understands meaning,
      so "what am I working on" finds a fact stored as "user_project: cyrrus".
    - Keyword fallback: word overlap scoring, used when fastembed isn't installed.

    Pass an embedder to use semantic retrieval without loading a second model:

        bot = Projector(config, llm_call=my_llm,
                        memory=MemoryVault(embedder=my_router.model))
    """

    def __init__(
        self,
        db_path: str = "slides_memory.db",
        max_facts_per_session: int = 500,
        max_fact_value_length: int = 2000,
        embedder: object = None,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
        backend: Optional[MemoryBackend] = None,
    ):
        self.max_facts_per_session = max_facts_per_session
        self.max_fact_value_length = max_fact_value_length
        self._embedder = embedder
        self._np = None

        if embedder is not None:
            self._try_load_numpy()
        else:
            self._try_load_embedder(embedding_model)

        # Use provided backend or default to SQLite (singleton per DB path)
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

    async def retrieve(self, session_id: str, user_input: str, limit: int = 3) -> list:
        validate_session_id(session_id)
        await self._ensure_initialized()
        rows = await self._backend.retrieve_current(session_id, limit=100)
        if not rows:
            return []

        if self._embedder is not None and self._np is not None:
            slides = await self._semantic_retrieve(rows, user_input, limit)
        else:
            slides = self._keyword_retrieve(rows, user_input, limit)

        if slides:
            touched = [s.id.replace("mem_", "") for s in slides]
            await self._backend.touch(session_id, touched)

        return slides

    async def _semantic_retrieve(self, rows: list, user_input: str, limit: int) -> list:
        try:
            # Embed each fact as "key: value" so the model understands context.
            # "user_project: cyrrus library" embeds much better than just "cyrrus library".
            fact_texts = [
                f"{kw.replace('_', ' ')}: {val}" if val else kw.replace("_", " ")
                for kw, val, _ in rows
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

            ranked = sorted(
                enumerate(scores), key=lambda x: x[1], reverse=True
            )[:limit]

            slides = []
            for idx, score in ranked:
                if score < 0.2:  # don't inject completely unrelated facts
                    continue
                kw, val, tok = rows[idx]
                slides.append(Slide(
                    id=f"mem_{kw}",
                    type="memory",
                    content=f"Fact: {val}",
                    tokens=tok,
                    priority=800,
                ))
            return slides

        except Exception as e:
            log.warning("Semantic retrieval failed (%s) — falling back to keywords.", e)
            return self._keyword_retrieve(rows, user_input, limit)

    def _keyword_retrieve(self, rows: list, user_input: str, limit: int) -> list:
        ranked = bm25_rank_facts(rows, user_input, limit=limit, score_threshold=0.0)
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
