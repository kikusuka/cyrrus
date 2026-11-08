"""Item 5 (v8): hybrid retrieval, OpenAI-compatible embeddings, RRF, fallback."""
import asyncio
import json
import logging
import math
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cyrrus import embeddings
from cyrrus.embeddings import OpenAIEmbedder, SQLiteEmbeddingStore, cosine_similarity
from cyrrus.hybrid import HybridRetriever
from cyrrus.memory import MemoryVault
from cyrrus.plugins import resolve_plugin
from cyrrus.projector import Projector


def _unit(cosine):
    return [cosine, math.sqrt(max(0.0, 1.0 - cosine ** 2))]


class FakeEmbedder:
    """Deterministic embedder; records every text batch it is asked for."""

    model = "fake-embed"

    def __init__(self, vectors, default=(0.0, 0.0)):
        self.vectors = vectors
        self.default = list(default)
        self.calls = []

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        return [list(self.vectors.get(text, self.default)) for text in texts]


class FailingEmbedder:
    model = "boom"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        raise RuntimeError("embedding endpoint unavailable")


def test_hybrid_rrf_combines_keyword_and_embedding():
    fake = FakeEmbedder({
        "what is my name": [1.0, 0.0],
        "user name: Alice": [0.0, 1.0],
        "vehicle: bicycle": [1.0, 0.0],
    })
    hybrid = HybridRetriever(embedder=fake)
    rows = hybrid.rank(
        [("user_name", "Alice", 1), ("vehicle", "bicycle", 1)],
        "what is my name",
        limit=2,
    )
    assert len(rows) == 2
    assert all(len(row) == 4 for row in rows)
    assert rows[0][1] == "user_name", rows
    assert rows[1][1] == "vehicle", rows
    # The fused score is an RRF score, not a raw BM25/cosine score.
    assert 0 < rows[0][0] < 1


def test_embedding_only_match_is_returned_without_lexical_overlap():
    fake = FakeEmbedder({
        "which municipality do I reside in": [1.0, 0.0],
        "residence town: Braga": [0.98, math.sqrt(1 - 0.98 ** 2)],
        "noise: unrelated": [0.0, 1.0],
    })
    hybrid = HybridRetriever(embedder=fake, min_similarity=0.5)
    rows = hybrid.rank(
        [("residence_town", "Braga", 1), ("noise", "unrelated", 1)],
        "which municipality do I reside in",
        limit=1,
    )
    assert rows and rows[0][1] == "residence_town"


def test_fallback_to_bm25_logs_once(caplog):
    caplog.set_level(logging.WARNING, logger="cyrrus.hybrid")
    hybrid = HybridRetriever(embedder=FailingEmbedder())
    facts = [("user_name", "Alice", 1)]
    first = hybrid.rank(facts, "what is my name", limit=1)
    second = hybrid.rank(facts, "what is my name", limit=1)
    assert first and first[0][1] == "user_name"
    assert second and second[0][1] == "user_name"
    warnings = [
        r for r in caplog.records
        if r.name == "cyrrus.hybrid" and "falling back" in r.getMessage().lower()
    ]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]


def test_sqlite_embedding_store_roundtrip_and_blob(tmp_path):
    db_path = str(tmp_path / "vectors.db")
    store = SQLiteEmbeddingStore(db_path)
    facts = [("user_name", "Alice", 1)]
    store.put("s", "fake-embed", facts, [[0.25, 0.75]])
    got = store.get("s", "fake-embed", facts)
    assert got["user_name"] == pytest.approx([0.25, 0.75])

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT vector, dim FROM fact_embeddings WHERE session_id=? AND keyword=?",
            ("s", "user_name"),
        ).fetchone()
    assert row is not None
    assert isinstance(row[0], bytes), "vectors must be stored as SQLite BLOBs"
    assert row[1] == 2
    # A changed value invalidates the cached vector.
    assert store.get("s", "fake-embed", [("user_name", "Alicia", 1)]) == {}


def test_hybrid_reuses_cached_fact_embeddings(tmp_path):
    fake = FakeEmbedder({
        "what is my name": [1.0, 0.0],
        "user name: Alice": [1.0, 0.0],
    })
    hybrid = HybridRetriever(
        embedder=fake, db_path=str(tmp_path / "cache.db"), session_id="s"
    )
    facts = [("user_name", "Alice", 1)]
    hybrid.rank(facts, "what is my name", limit=1)
    hybrid.rank(facts, "what is my name", limit=1)
    first_batch, second_batch = fake.calls[0], fake.calls[1]
    assert "user name: Alice" in first_batch
    assert "user name: Alice" not in second_batch
    assert "what is my name" in second_batch


def test_cosine_optional_numpy(monkeypatch):
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    monkeypatch.setattr(embeddings, "_np", None)
    assert cosine_similarity([0.6, 0.8], [0.6, 0.8]) == pytest.approx(1.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


def test_openai_compatible_embedding_request():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = body
            payload = {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%d/v1" % server.server_port
        embedder = OpenAIEmbedder(
            base_url=base, model="fake-model", api_key="secret", timeout=2.0
        )
        vectors = embedder.embed(["first", "second"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]  # ordered by response index
    assert seen["path"] == "/v1/embeddings"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["model"] == "fake-model"
    assert seen["body"]["input"] == ["first", "second"]


def test_builtin_hybrid_plugin_uses_embedder_config(tmp_path):
    fake = FakeEmbedder({
        "what is my name": [1.0, 0.0],
        "user name: Alice": [1.0, 0.0],
    })
    plugin = resolve_plugin(
        "retriever",
        "hybrid",
        {"embedder": fake, "db_path": str(tmp_path / "plugin.db")},
    )
    assert isinstance(plugin, HybridRetriever)
    rows = plugin.rank([("user_name", "Alice", 1)], "what is my name", limit=1)
    assert rows and rows[0][1] == "user_name"


def test_projector_config_selects_hybrid_retriever(tmp_path):
    fake = FakeEmbedder({
        "where do I live": [1.0, 0.0],
        "user location: Lisbon": [1.0, 0.0],
    })

    async def fake_llm(messages):
        return "ok"

    db_path = str(tmp_path / "projector.db")
    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=fake_llm,
        memory_db_path=db_path,
        plugins={
            "retriever": "hybrid",
            "hybrid": {"embedder": fake, "db_path": db_path},
        },
        min_relative_score=0.0,
    )
    assert isinstance(bot.memory._retriever, HybridRetriever)
    asyncio.run(bot.memory.upsert("s", "user_location", "Lisbon", 1))
    slides = asyncio.run(bot.memory.retrieve("s", "where do I live", limit=1))
    assert slides and slides[0].id == "mem_user_location"


def test_memory_vault_with_hybrid_retriever_is_unchanged_without_embedder(tmp_path):
    vault = MemoryVault(
        db_path=str(tmp_path / "keyword.db"),
        retriever=HybridRetriever(embedder=None),
    )
    asyncio.run(vault.upsert("s", "user_name", "Alice", 1))
    slides = asyncio.run(vault.retrieve("s", "what is my name", limit=1))
    assert slides and slides[0].id == "mem_user_name"
