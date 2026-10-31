import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from cyrrus.config import validate_config
from cyrrus.gateway import Gateway, create_server
from cyrrus.projector import Projector


async def _llm(messages):
    return "unused"


def _projector(tmp_path):
    return Projector(
        {"core_lamp": {"content": "Be concise."}, "weather": {"content": "Weather slide.", "triggers": ["weather"]}},
        _llm, memory_db_path=str(tmp_path / "memory.sqlite"),
    )


def _config():
    return validate_config({"provider": {"base_url": "http://127.0.0.1:9/v1", "model": "test-model"}})


def test_public_context_and_record_turn(tmp_path):
    async def run():
        projector = _projector(tmp_path)
        context, trace = await projector.build_context("weather please", "alpha")
        assert "Weather slide." in context
        assert trace["session_id"] == "alpha"
        await projector.record_turn("alpha", "my name is Ada", "hello")
        facts = await projector.memory.retrieve("alpha", "name")
        assert facts
    asyncio.run(run())


def test_gateway_injects_model_session_and_skip(tmp_path):
    gateway = Gateway(_config(), projector=_projector(tmp_path))
    payload = {"model": "cyrrus", "user": "user-id", "messages": [{"role": "user", "content": "weather please"}]}
    outgoing, session, _, trace = gateway.prepare(payload, {})
    assert session == "user-id"
    assert outgoing["messages"][0]["role"] == "system"
    assert "Weather slide." in outgoing["messages"][0]["content"]
    bypass, _, _, trace = gateway.prepare(payload, {"X-Cyrrus-Skip": "1"})
    assert bypass == payload and trace["skipped"]


def test_tools_are_not_altered(tmp_path):
    gateway = Gateway(_config(), projector=_projector(tmp_path))
    payload = {"model": "test", "tools": [{"type": "function"}], "messages": [{"role": "user", "content": "weather"}]}
    outgoing, _, _, _ = gateway.prepare(payload, {})
    assert outgoing["messages"] == payload["messages"]


def test_non_loopback_requires_key():
    with pytest.raises(ValueError, match="Non-loopback"):
        create_server(_config(), host="0.0.0.0")


def test_status_and_last_do_not_contain_prompt(tmp_path):
    server = create_server(_config(), projector=_projector(tmp_path), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = "http://127.0.0.1:%s" % server.server_address[1]
        assert json.load(urlopen(base + "/health"))["status"] == "ok"
        server.gateway.add_trace("s", {"session_id": "s", "user_input": "private", "system_message": "secret", "stats": {}}, 0)
        dumped = json.dumps(json.load(urlopen(base + "/cyrrus/last")))
        assert "private" not in dumped and "secret" not in dumped
    finally:
        server.shutdown(); server.server_close()
