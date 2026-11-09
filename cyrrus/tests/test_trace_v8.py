import json
import threading
from urllib.request import urlopen

import pytest

from cyrrus.config import validate_config
from cyrrus.gateway import create_server
from cyrrus.memory import MemoryVault
from cyrrus.projector import Projector
from cyrrus.trace import Trace


async def _llm(messages):
    return "unused"


def _projector(tmp_path, **kwargs):
    return Projector(
        {"core_lamp": {"content": "Be concise."}},
        _llm,
        memory_db_path=str(tmp_path / "trace_memory.sqlite"),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_trace_lists_every_ranked_candidate(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "trace.db"))
    for i in range(5):
        await vault.upsert("s", "note_%d" % i, "python coffee note %d" % i, 4)

    trace = Trace(session_id="s")
    slides = await vault.retrieve("s", "python coffee", limit=2, trace=trace)

    assert len(slides) == 2
    assert len(trace.candidates) == 5, trace.to_dict()
    assert all(c["score"] > 0 for c in trace.to_dict()["candidates"])
    included = [c for c in trace.to_dict()["candidates"] if c["included"]]
    dropped = [c for c in trace.to_dict()["candidates"] if not c["included"]]
    assert len(included) == 2
    assert len(dropped) == 3
    assert all(c.get("reason") for c in included)
    assert all(c.get("dropped_reason") for c in dropped)
    # Values are prompt text and must be absent by default.
    assert all("value" not in c for c in trace.to_dict()["candidates"])


@pytest.mark.asyncio
async def test_trace_values_opt_in(tmp_path):
    vault = MemoryVault(db_path=str(tmp_path / "trace_values.db"))
    await vault.upsert("s", "user_location", "Braga", 2)

    trace = Trace(session_id="s", include_values=True)
    await vault.retrieve("s", "where do I live?", limit=1, trace=trace)
    assert trace.to_dict()["candidates"][0]["value"] == "Braga"


@pytest.mark.asyncio
async def test_library_last_trace_is_callable_and_value_free(tmp_path):
    bot = _projector(tmp_path)
    await bot.memory.upsert("s", "user_location", "Braga", 2)

    await bot.build_context("where do I live?", "s")
    trace = bot.last_trace()
    assert trace is bot.last_trace
    assert trace["session_id"] == "s"
    assert trace["candidates"]
    assert any(c["source"] == "fact" for c in trace["candidates"])
    assert all("value" not in c for c in trace["candidates"])


def test_gateway_last_exposes_candidates_without_values(tmp_path):
    config = validate_config({"provider": {"model": "test-model"}})
    projector = _projector(tmp_path)
    server = create_server(config, projector=projector, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        server.gateway._submit(projector.memory.upsert("s", "user_location", "Braga", 2))
        _, _, _, trace = server.gateway.prepare(
            {"messages": [{"role": "user", "content": "where do I live?"}]},
            {"X-Cyrrus-Session": "s"},
        )
        server.gateway.add_trace("s", trace, 0)
        payload = json.load(urlopen(base + "/cyrrus/last"))
        item = payload["requests"][-1]
        assert item["candidates"], item
        assert any(c["source"] == "fact" for c in item["candidates"])
        dumped = json.dumps(item)
        assert "Braga" not in dumped
    finally:
        server.shutdown()
        server.server_close()

