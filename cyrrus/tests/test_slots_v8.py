"""Item 4 (v8): Retriever/Packer protocols, plugin discovery, conformance helpers."""
import asyncio

import pytest

from cyrrus import plugins
from cyrrus.bm25_index import SessionFactIndex
from cyrrus.backend import MemoryBackend
from cyrrus.config import validate_config
from cyrrus.knapsack import TokenKnapsack
from cyrrus.memory import MemoryVault
from cyrrus.plugins import BM25Retriever, Packer, Retriever, resolve_plugin
from cyrrus.projector import Projector
from cyrrus.sqlite_backend import SQLiteBackend
from cyrrus.testing import check_backend, check_retriever


class ToyRetriever:
    """Ranks the fact named plugin_choice first, ignoring the query."""

    def __init__(self):
        self.calls = []

    def rank(self, facts, query, limit=3, score_threshold=0.0, **kwargs):
        self.calls.append((list(facts), query, limit))
        chosen = [f for f in facts if f[0] == "plugin_choice"]
        rest = [f for f in facts if f[0] != "plugin_choice"]
        rows = [(1.0,) + tuple(f) for f in chosen + rest]
        return [r for r in rows if r[0] > score_threshold][:limit]


class ToyPacker:
    """Packs at most one slide so tests can observe the selected packer."""

    def pack(self, candidates, budget):
        return list(candidates)[:1]


class _FakeEntryPoint:
    def __init__(self, name, loaded):
        self.name = name
        self._loaded = loaded

    def load(self):
        return self._loaded


@pytest.fixture()
def fake_entry_points(monkeypatch):
    mapping = {
        "toy_retriever": ToyRetriever,
        "toy_packer": ToyPacker,
        "toy_sqlite": SQLiteBackend,
    }

    def _iter(group=plugins.PLUGIN_GROUP):
        assert group == "cyrrus.plugins"
        return [_FakeEntryPoint(name, obj) for name, obj in mapping.items()]

    monkeypatch.setattr(plugins, "_iter_entry_points", _iter)
    return mapping


def test_protocol_defaults_and_fact_ranking():
    retriever = BM25Retriever()
    assert isinstance(retriever, Retriever)
    assert isinstance(TokenKnapsack(), Packer)

    ranked = retriever.rank(
        [("user_location", "I live in Lisbon", 5), ("note_1", "weather", 1)],
        "where do I live",
        limit=2,
    )
    assert ranked and ranked[0][1] == "user_location"
    assert all(len(row) == 4 for row in ranked)


def test_fake_entry_point_discovery_and_selection(fake_entry_points):
    names = set(plugins.list_plugins())
    assert {"toy_retriever", "toy_packer", "toy_sqlite"} <= names
    toy = resolve_plugin("retriever", "toy_retriever")
    assert isinstance(toy, ToyRetriever)

    ranked = toy.rank(
        [("plugin_choice", "x", 1), ("other", "y", 1)], "anything", limit=2
    )
    assert ranked[0][1] == "plugin_choice"


def test_config_selects_retriever_and_packer(fake_entry_points, tmp_path):
    cfg = validate_config(
        {"plugins": {"retriever": "toy_retriever", "packer": "toy_packer"}}
    )

    async def fake_llm(messages):
        return "ok"

    bot = Projector(
        {"core_lamp": {"content": "You are helpful."}},
        llm_call=fake_llm,
        memory_db_path=str(tmp_path / "plugins.db"),
        plugins=cfg["plugins"],
        min_relative_score=0.0,
    )
    assert isinstance(bot.memory._retriever, ToyRetriever)
    assert isinstance(bot.knapsack, ToyPacker)

    asyncio.run(bot.memory.upsert("s", "plugin_choice", "selected", 1))
    asyncio.run(bot.memory.upsert("s", "other", "not selected", 2))
    slides = asyncio.run(bot.memory.retrieve("s", "anything", limit=2))
    assert slides[0].id == "mem_plugin_choice"
    assert bot.memory._retriever.calls


def test_retriever_plugin_can_be_passed_directly(fake_entry_points, tmp_path):
    toy = ToyRetriever()
    vault = MemoryVault(db_path=str(tmp_path / "direct.db"), retriever=toy)
    asyncio.run(vault.upsert("s", "plugin_choice", "selected", 1))
    asyncio.run(vault.upsert("s", "other", "not selected", 2))
    slides = asyncio.run(vault.retrieve("s", "anything", limit=2))
    assert slides[0].id == "mem_plugin_choice"
    assert toy.calls


def test_backend_conformance_and_plugin_selection(fake_entry_points, tmp_path):
    backend = resolve_plugin(
        "backend", "toy_sqlite", {"db_path": str(tmp_path / "conf.db")}
    )
    assert isinstance(backend, MemoryBackend)
    check_backend(backend)

    check_retriever(BM25Retriever())


def test_conformance_helper_rejects_bad_retriever():
    class BadRetriever:
        def rank(self, facts, query, limit=3, score_threshold=0.0, **kwargs):
            return [("not-a-tuple",)]

    with pytest.raises(AssertionError):
        check_retriever(BadRetriever())


def test_default_sessionfactindex_matches_retriever_contract():
    index = SessionFactIndex([("user_location", "Lisbon", 1)])
    ranked, _dropped = index.rank("Lisbon", limit=1)
    assert isinstance(ranked[0][0], float)
    assert ranked[0][1] == "user_location"


def test_config_rejects_bad_plugin_selection():
    with pytest.raises(ValueError):
        validate_config({"plugins": {"retriever": 3}})
    with pytest.raises(ValueError):
        validate_config({"plugins": {"packer": ""}})
