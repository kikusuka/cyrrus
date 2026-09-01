import asyncio
import logging
import re
import sqlite3
import time
from .data import Slide

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
        max_fact_value_length: int = 500,
        embedder: object = None,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
    ):
        self.db_path = db_path
        self.max_facts_per_session = max_facts_per_session
        self.max_fact_value_length = max_fact_value_length
        self._embedder = embedder
        self._np = None

        if embedder is not None:
            self._try_load_numpy()
        else:
            self._try_load_embedder(embedding_model)

        self._init_db()

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

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # WAL mode cuts concurrent read latency significantly.
            # Without it, 300 concurrent users hit ~1.4s median / 5s worst-case.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    session_id    TEXT NOT NULL,
                    keyword       TEXT NOT NULL,
                    value         TEXT,
                    tokens        INTEGER,
                    last_accessed REAL,
                    PRIMARY KEY (session_id, keyword)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON facts(session_id)")

    async def upsert(self, session_id: str, keyword: str, value: str, tokens: int):
        if value and len(value) > self.max_fact_value_length:
            log.warning(
                "Fact '%s' (session %s) truncated from %d to %d chars.",
                keyword, session_id, len(value), self.max_fact_value_length,
            )
            value = value[:self.max_fact_value_length].rsplit(" ", 1)[0] + "..."
            tokens = min(tokens, len(value.split()))

        def _write():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?)",
                        (session_id, keyword, value, tokens, time.time()),
                    )
                    count = conn.execute(
                        "SELECT COUNT(*) FROM facts WHERE session_id=?", (session_id,)
                    ).fetchone()[0]
                    if count > self.max_facts_per_session:
                        overflow = count - self.max_facts_per_session
                        conn.execute("""
                            DELETE FROM facts WHERE rowid IN (
                                SELECT rowid FROM facts WHERE session_id=?
                                ORDER BY last_accessed ASC LIMIT ?
                            )
                        """, (session_id, overflow))
            except sqlite3.OperationalError:
                # DB was deleted or corrupted mid-write — recreate and retry once.
                self._init_db()
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?)",
                        (session_id, keyword, value, tokens, time.time()),
                    )

        await asyncio.to_thread(_write)

    async def retrieve(self, session_id: str, user_input: str, limit: int = 3) -> list:
        def _read():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    return conn.execute(
                        "SELECT keyword, value, tokens FROM facts "
                        "WHERE session_id=? ORDER BY last_accessed DESC LIMIT 100",
                        (session_id,),
                    ).fetchall()
            except sqlite3.OperationalError:
                # DB was deleted or corrupted — recreate it and return empty.
                self._init_db()
                return []

        rows = await asyncio.to_thread(_read)
        if not rows:
            return []

        if self._embedder is not None and self._np is not None:
            slides = await self._semantic_retrieve(rows, user_input, limit)
        else:
            slides = self._keyword_retrieve(rows, user_input, limit)

        if slides:
            touched = [s.id.replace("mem_", "") for s in slides]
            await self._touch(session_id, touched)

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
        user_words = set(re.findall(r"\w+", user_input.lower()))
        scored = []
        for kw, val, tok in rows:
            kw_words = set(re.findall(r"\w+", kw.replace("_", " ").lower()))
            val_words = set(re.findall(r"\w+", val.lower())) if val else set()
            score = len(user_words & kw_words) + len(user_words & val_words)
            if score > 0:
                scored.append((score, kw, val, tok))

        scored.sort(reverse=True)
        return [
            Slide(
                id=f"mem_{kw}",
                type="memory",
                content=f"Fact: {val}",
                tokens=tok,
                priority=800,
            )
            for _, kw, val, tok in scored[:limit]
        ]

    async def _touch(self, session_id: str, keywords: list):
        def _write():
            with sqlite3.connect(self.db_path) as conn:
                now = time.time()
                conn.executemany(
                    "UPDATE facts SET last_accessed=? WHERE session_id=? AND keyword=?",
                    [(now, session_id, kw) for kw in keywords],
                )
        await asyncio.to_thread(_write)

    async def delete_session(self, session_id: str) -> int:
        """
        Delete all facts for a given session. Useful for GDPR compliance
        (right to be forgotten) and session cleanup.

        Returns the number of facts deleted.
        """
        def _write():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute(
                        "DELETE FROM facts WHERE session_id=?",
                        (session_id,)
                    )
                    return cursor.rowcount
            except sqlite3.OperationalError:
                # DB was deleted or corrupted — recreate and retry once.
                self._init_db()
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.execute(
                        "DELETE FROM facts WHERE session_id=?",
                        (session_id,)
                    )
                    return cursor.rowcount

        return await asyncio.to_thread(_write)
