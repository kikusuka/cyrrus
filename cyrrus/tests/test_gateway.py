import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
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


def _fake_upstream():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.endswith("/models"):
                data = b'{"object":"list","data":[{"id":"upstream-model"}]}'
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)
            else:
                self.send_error(404)

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            self.server.bodies.append(json.loads(self.rfile.read(length)))
            if self.path.endswith("/error") or self.server.error:
                self.send_response(429); self.end_headers(); self.wfile.write(b'{"error":"limited"}'); return
            stream = self.server.bodies[-1].get("stream")
            self.send_response(200); self.send_header("Content-Type", "text/event-stream" if stream else "application/json"); self.end_headers()
            if stream:
                for word in ("one", " two"):
                    self.wfile.write(("data: {\"choices\":[{\"delta\":{\"content\":\"%s\"}}]}\n\n" % word).encode()); self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.bodies, server.error = [], False
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    return server


def _request(base, payload, headers=None):
    request = Request(base + "/v1/chat/completions", data=json.dumps(payload).encode(), headers=headers or {"Content-Type": "application/json"})
    return urlopen(request)


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


def test_proxy_nonstream_stream_models_and_model_rules(tmp_path):
    upstream = _fake_upstream()
    config = _config(); config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    server = create_server(config, projector=_projector(tmp_path), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]
    try:
        assert json.load(_request(base, {"model": "cyrrus", "messages": [{"role": "user", "content": "weather"}]}))["choices"][0]["message"]["content"] == "ok"
        assert upstream.bodies[-1]["model"] == "test-model"
        assert "Weather slide." in upstream.bodies[-1]["messages"][0]["content"]
        stream = _request(base, {"model": "any", "stream": True, "messages": [{"role": "user", "content": "weather"}]}).read().decode()
        assert "one" in stream and " two" in stream and "[DONE]" in stream
        assert json.load(urlopen(base + "/v1/models"))["data"][0]["id"] == "upstream-model"
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


def test_proxy_tools_skip_fail_open_and_manage(tmp_path, monkeypatch):
    upstream = _fake_upstream()
    config = _config(); config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]; config["context"]["max_context_tokens"] = 8; config["gateway"]["mode"] = "manage"
    projector = _projector(tmp_path)
    server = create_server(config, projector=projector, port=0); thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]
    try:
        tools = {"model": "x", "tools": [{"type": "function"}], "messages": [{"role": "user", "content": "weather"}]}
        _request(base, tools).read(); assert upstream.bodies[-1]["messages"] == tools["messages"]
        skipped = {"model": "x", "messages": [{"role": "user", "content": "weather"}]}
        _request(base, skipped, {"Content-Type": "application/json", "X-Cyrrus-Skip": "1"}).read(); assert upstream.bodies[-1]["messages"] == skipped["messages"]
        messages = [{"role": "system", "content": "keep"}] + [{"role": "user", "content": "old old old"}] * 4 + [{"role": "assistant", "content": "latest"}]
        _request(base, {"model": "x", "messages": messages}).read(); assert upstream.bodies[-1]["messages"][0]["role"] == "system"; assert upstream.bodies[-1]["messages"][-1]["content"] == "latest"
        monkeypatch.setattr(projector, "build_context", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
        _request(base, skipped).read(); assert upstream.bodies[-1]["messages"] == skipped["messages"]
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()
