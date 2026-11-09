"""Stdlib-only embedding support for hybrid retrieval (v8 item 5).

Two pieces live here:

* :class:`OpenAIEmbedder` - a tiny client for the OpenAI-compatible
  ``POST {base_url}/embeddings`` endpoint using ``urllib`` only. Works with
  OpenAI, Ollama, vLLM, LM Studio, and other compatible servers.
* :class:`SQLiteEmbeddingStore` - a small SQLite cache that stores vectors as
  BLOBs. Vectors are keyed by ``(session_id, keyword, model)`` and invalidated
  when the fact value changes.

Cosine similarity uses numpy when it is installed and pure Python otherwise.
No new required dependency is introduced.
"""
from __future__ import annotations

import json
import math
import os
import socket
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # optional, used only to speed up cosine math
    import numpy as _np
except ImportError:  # pragma: no cover - exercised in no-numpy runs
    _np = None


def _default_db_path() -> str:
    from .sqlite_backend import default_db_path

    return default_db_path()


def _pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack("<%df" % len(vector), *[float(x) for x in vector])


def _unpack_vector(blob: bytes, dim: int) -> List[float]:
    return list(struct.unpack("<%df" % dim, blob))


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-length vectors.

    Returns 0.0 when either vector has zero norm instead of raising, because
    embedding servers occasionally return an all-zero vector for empty input.
    """
    if len(a) != len(b):
        raise ValueError(
            "vector length mismatch: %d != %d" % (len(a), len(b))
        )
    if not a:
        return 0.0
    if _np is not None:
        av = _np.asarray(a, dtype=float)
        bv = _np.asarray(b, dtype=float)
        denom = float(_np.linalg.norm(av) * _np.linalg.norm(bv))
        if denom == 0.0:
            return 0.0
        return float(av.dot(bv) / denom)
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    denom = norm_a * norm_b
    if denom == 0.0:
        return 0.0
    return dot / denom


class OpenAIEmbedder:
    """OpenAI-compatible embeddings over stdlib ``urllib``.

    Args:
        base_url: Server root (for example ``http://localhost:11434/v1``). If
            it already ends with ``/embeddings`` it is used as-is.
        model: Embedding model name sent in the request body.
        api_key: Optional bearer token. If omitted, no Authorization header is
            sent unless ``api_key_env`` is provided.
        api_key_env: Environment variable holding the bearer token.
        timeout: Per-request socket timeout in seconds.
        batch_size: Maximum number of texts per HTTP request.
        dimensions: Optional embedding dimension sent to compatible servers.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        timeout: float = 10.0,
        batch_size: int = 64,
        dimensions: Optional[int] = None,
    ):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("embedding base_url is required")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("embedding model is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.endpoint = self.base_url
        if not self.endpoint.endswith("/embeddings"):
            self.endpoint += "/embeddings"
        self.timeout = float(timeout)
        self.batch_size = max(1, int(batch_size))
        self.dimensions = dimensions
        self.api_key = api_key
        if api_key_env:
            self.api_key = os.environ.get(api_key_env)
        # Observability for honest cost reporting; no dollar figures implied.
        self.request_count = 0
        self.text_count = 0
        self.input_tokens = 0
        self.total_tokens = 0

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request(self, batch: List[str]) -> List[List[float]]:
        payload: Dict[str, Any] = {"model": self.model, "input": batch}
        if self.dimensions is not None:
            payload["dimensions"] = int(self.dimensions)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise RuntimeError(
                "embedding API HTTP %s: %s" % (exc.code, detail)
            ) from exc
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            raise RuntimeError("embedding API request failed: %s" % (exc,)) from exc

        try:
            obj = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("embedding API returned malformed JSON") from exc
        data = obj.get("data") if isinstance(obj, dict) else None
        if not isinstance(data, list):
            raise RuntimeError("embedding API response has no data list")

        # OpenAI-compatible servers may return items out of order; sort by
        # index when available, otherwise trust list order.
        try:
            ordered = sorted(
                data,
                key=lambda item: item.get("index", 0),
            )
        except AttributeError as exc:
            raise RuntimeError("embedding API returned malformed rows") from exc
        vectors: List[List[float]] = []
        for item in ordered:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("embedding API returned an empty vector")
            try:
                vectors.append([float(x) for x in vector])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("embedding API returned non-numeric values") from exc
        if len(vectors) != len(batch):
            raise RuntimeError(
                "embedding API returned %d vectors for %d inputs"
                % (len(vectors), len(batch))
            )
        usage = obj.get("usage") if isinstance(obj, dict) else None
        if isinstance(usage, dict):
            self.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self.total_tokens += int(usage.get("total_tokens", 0) or 0)
        return vectors

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        """Embed *texts* preserving input order."""
        texts = [str(text) for text in texts]
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            vectors.extend(self._request(batch))
            self.request_count += 1
            self.text_count += len(batch)
        return vectors


class SQLiteEmbeddingStore:
    """Persistent SQLite BLOB cache for fact embeddings.

    The cache is intentionally separate from the ``facts`` table so a backend
    can keep its existing schema. The primary key is
    ``(session_id, keyword, model)``; a row is ignored when its stored value no
    longer matches the current fact value, so supersession automatically
    triggers a re-embed.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_db_path()
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self):
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return conn

    def _ensure_table(self, conn) -> None:
        if self._initialized:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fact_embeddings (
                session_id TEXT NOT NULL,
                keyword    TEXT NOT NULL,
                model      TEXT NOT NULL,
                value      TEXT,
                dim        INTEGER NOT NULL,
                vector     BLOB NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (session_id, keyword, model)
            )
            """
        )
        conn.commit()
        self._initialized = True

    def get(
        self,
        session_id: str,
        model: str,
        facts: Sequence[Tuple[str, str, int]],
    ) -> Dict[str, List[float]]:
        """Return cached vectors for *facts* (only matching current values)."""
        if not facts:
            return {}
        expected = {keyword: value for keyword, value, _tokens in facts}
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_table(conn)
                rows = conn.execute(
                    "SELECT keyword, value, dim, vector FROM fact_embeddings "
                    "WHERE session_id=? AND model=?",
                    (session_id, model),
                ).fetchall()
            finally:
                conn.close()
        cached: Dict[str, List[float]] = {}
        for keyword, value, dim, blob in rows:
            if keyword not in expected:
                continue
            if (expected[keyword] or "") != (value or ""):
                continue
            try:
                cached[keyword] = _unpack_vector(blob, int(dim))
            except (struct.error, TypeError):
                continue
        return cached

    def put(
        self,
        session_id: str,
        model: str,
        facts: Sequence[Tuple[str, str, int]],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """Store or replace vectors for *facts*."""
        if len(facts) != len(vectors):
            raise ValueError("facts and vectors must have the same length")
        if not facts:
            return
        rows = []
        now = time.time()
        for (keyword, value, _tokens), vector in zip(facts, vectors):
            rows.append(
                (
                    session_id,
                    keyword,
                    model,
                    value,
                    len(vector),
                    _pack_vector(vector),
                    now,
                )
            )
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_table(conn)
                conn.executemany(
                    "INSERT OR REPLACE INTO fact_embeddings "
                    "(session_id, keyword, model, value, dim, vector, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()

    def delete_session(self, session_id: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_table(conn)
                cursor = conn.execute(
                    "DELETE FROM fact_embeddings WHERE session_id=?",
                    (session_id,),
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
