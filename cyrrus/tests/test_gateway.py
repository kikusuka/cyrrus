import asyncio
import http.client
import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cyrrus.config import validate_config
from cyrrus.gateway import Gateway, create_server
from cyrrus.projector import Projector


async def _llm(messages):
    return "unused"


def _projector(tmp_path, **kwargs):
    return Projector(
        {"core_lamp": {"content": "Be concise."}, "weather": {"content": "Weather slide.", "triggers": ["weather"]}},
        _llm, memory_db_path=str(tmp_path / "memory.sqlite"), **kwargs
    )


def _config():
    return validate_config({"provider": {"base_url": "http://127.0.0.1:9/v1", "model": "test-model"}})


class _UpstreamServer(ThreadingHTTPServer):
    """Fake upstream sized to absorb 200 simultaneous forwarded requests.

    The stdlib default listen backlog (5) makes a plain ThreadingHTTPServer
    refuse the tail of a 200-way burst; that is a harness limit, not the thing
    under test, so raise it (and keep handler threads daemon) here.
    """
    daemon_threads = True
    request_queue_size = 512


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
                first = ("data: {\"choices\":[{\"delta\":{\"content\":\"%s\"}}]}\n\n" % "one").encode()
                self.wfile.write(first); self.wfile.flush()
                if self.server.stream_gate is not None:
                    self.server.first_sent.set()
                    self.server.stream_gate.wait(5)
                self.wfile.write(b"data: {\"choices\":[{\"delta\":{\"content\":\" two\"}}]}\n\n"); self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')
    server = _UpstreamServer(("127.0.0.1", 0), Handler)
    server.bodies, server.error = [], False
    server.stream_gate = None
    server.first_sent = threading.Event()
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


def _start(config, projector):
    server = create_server(config, projector=projector, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%s" % server.server_address[1]


def _with_upstream(tmp_path):
    upstream = _fake_upstream()
    config = _config()
    config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    server, base = _start(config, _projector(tmp_path))
    return upstream, config, server, base


def test_upstream_error_status_and_body_pass_through(tmp_path):
    upstream, _, server, base = _with_upstream(tmp_path)
    upstream.error = True
    try:
        with pytest.raises(HTTPError) as exc:
            _request(base, {"model": "x", "messages": [{"role": "user", "content": "hi"}]})
        assert exc.value.code == 429
        assert b"limited" in exc.value.read()
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


def test_stream_is_forwarded_incrementally(tmp_path):
    upstream, _, server, base = _with_upstream(tmp_path)
    upstream.stream_gate = threading.Event()
    host, port = "127.0.0.1", server.server_address[1]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request(
            "POST", "/v1/chat/completions",
            body=json.dumps({"model": "x", "stream": True, "messages": [{"role": "user", "content": "hi"}]}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        first = response.readline()
        assert b"one" in first
        assert upstream.first_sent.wait(5)
        upstream.stream_gate.set()
        rest = response.read()
        assert b" two" in rest and b"[DONE]" in rest
    finally:
        conn.close(); server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


def test_model_rules_and_force_model(tmp_path):
    upstream, config, server, base = _with_upstream(tmp_path)
    try:
        for sent in ("", "cyrrus", "custom-model"):
            _request(base, {"model": sent, "messages": [{"role": "user", "content": "hi"}]}).read()
            expected = "custom-model" if sent == "custom-model" else "test-model"
            assert upstream.bodies[-1]["model"] == expected
        server.gateway.options["force_model"] = "forced-model"
        _request(base, {"model": "custom-model", "messages": [{"role": "user", "content": "hi"}]}).read()
        assert upstream.bodies[-1]["model"] == "forced-model"
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


def test_session_header_and_body_user(tmp_path):
    gateway = Gateway(_config(), projector=_projector(tmp_path))
    payload = {"user": "body-session", "messages": [{"role": "user", "content": "hi"}]}
    assert gateway.prepare(payload, {})[1] == "body-session"
    assert gateway.prepare(payload, {"X-Cyrrus-Session": "header-session"})[1] == "header-session"


def test_facts_learned_in_one_request_appear_in_next_system_message(tmp_path):
    upstream, _, server, base = _with_upstream(tmp_path)
    try:
        _request(base, {"model": "x", "user": "facts-session", "messages": [{"role": "user", "content": "my name is Ada"}]}).read()
        facts = []
        for _ in range(100):
            facts = asyncio.run(server.gateway.projector.memory.retrieve("facts-session", "name"))
            if facts:
                break
            time.sleep(0.05)
        assert facts, "fact extraction did not complete"
        _request(base, {"model": "x", "user": "facts-session", "messages": [{"role": "user", "content": "what is my name?"}]}).read()
        system = upstream.bodies[-1]["messages"][0]
        assert system["role"] == "system" and "Ada" in system["content"]
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


def test_manage_mode_compaction_uses_summarizer_and_keeps_protected(tmp_path):
    seen = {}

    def summarize(old):
        seen["old"] = old
        return "Summary of %d earlier messages" % len(old)

    projector = _projector(tmp_path, history_summarizer=summarize)
    config = _config()
    config["gateway"]["mode"] = "manage"
    config["context"]["max_context_tokens"] = 8
    gateway = Gateway(config, projector=projector)
    messages = (
        [{"role": "system", "content": "keep"}]
        + [{"role": "user", "content": "old old old"}] * 4
        + [{"role": "assistant", "content": "latest"}]
    )
    result = gateway._compact(messages)
    assert result[0] == {"role": "system", "content": "keep"}
    assert any(m["role"] == "system" and "Summary of" in m["content"] for m in result)
    assert result[-1]["content"] == "latest"
    assert seen["old"]


def test_manage_mode_summarizer_failure_falls_back_to_dropping(tmp_path):
    def summarize(old):
        raise RuntimeError("no model")

    projector = _projector(tmp_path, history_summarizer=summarize)
    config = _config()
    config["gateway"]["mode"] = "manage"
    config["context"]["max_context_tokens"] = 4
    gateway = Gateway(config, projector=projector)
    messages = [{"role": "system", "content": "keep"}] + [{"role": "user", "content": "old old"}] * 3 + [{"role": "assistant", "content": "latest"}]
    result = gateway._compact(messages)
    assert result[0]["content"] == "keep" and result[-1]["content"] == "latest"


def test_tool_messages_are_inject_only(tmp_path):
    gateway = Gateway(_config(), projector=_projector(tmp_path))
    payload = {"messages": [{"role": "user", "content": "hi"}, {"role": "tool", "content": "result"}]}
    outgoing, _, _, _ = gateway.prepare(payload, {})
    assert outgoing["messages"] == payload["messages"]


def test_request_body_limit(tmp_path, monkeypatch):
    import cyrrus.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "MAX_BODY", 32)
    upstream, _, server, _ = _with_upstream(tmp_path)
    host, port = "127.0.0.1", server.server_address[1]
    try:
        # Oversized 1 MB body, repeated: if the server answers 413 without
        # draining the request body, its socket close sends a TCP RST and the
        # client's read intermittently dies with ConnectionAbortedError
        # (WinError 10053 on Windows). No sleeps; determinism comes from the
        # server fully reading the request before it responds and closes.
        body = b"x" * (1024 * 1024)
        for _ in range(30):
            conn = http.client.HTTPConnection(host, port, timeout=10)
            try:
                conn.request(
                    "POST", "/v1/chat/completions", body=body,
                    headers={"Content-Type": "application/json",
                             "Content-Length": str(len(body))},
                )
                response = conn.getresponse()
                assert response.status == 413
                response.read()
            finally:
                conn.close()
    finally:
        server.shutdown(); server.server_close(); upstream.shutdown(); upstream.server_close()


# --------------------------------------------------------------------------- #
# Item 1 — gateway event-loop bug: shared asyncio primitives across per-request
# asyncio.run() loops must not cause cross-loop fail-opens under concurrency.
# --------------------------------------------------------------------------- #
def _seeded_projector(tmp_path, session, keyword, value):
    """Projector with one memory fact already stored for ``session``."""
    projector = _projector(tmp_path)
    asyncio.run(projector.memory.upsert(session, keyword, value, len(value.split())))
    return projector


def _concurrent_requests(base, n, session, text):
    """Fire ``n`` simultaneous POSTs (released together by a barrier).

    Returns (errors, codes). Each worker opens its own connection so the
    ThreadingHTTPServer dispatches one OS thread per request -- exactly the
    path that used to run a fresh asyncio loop per request.

    The cross-loop sharing this guards against is a genuine data race: with the
    default 5 ms GIL switch interval the tiny lock-held windows almost never
    overlap, so it stays latent.  ``sys.setswitchinterval`` shrinks that window
    so the race is exercised every run instead of occasionally; it is restored
    afterwards.  This does not change what is asserted, only how reliably the
    (already-present) concurrency bug is triggered.
    """
    errors, codes = [], []
    guard = threading.Lock()
    barrier = threading.Barrier(n, timeout=120)
    host, port = base.split("//", 1)[1].split(":", 1)
    port = int(port)

    def worker():
        try:
            barrier.wait()
        except threading.BrokenBarrierError as exc:
            with guard:
                errors.append("barrier %r" % exc)
            return
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=30)
            conn.request(
                "POST", "/v1/chat/completions",
                body=json.dumps({"model": "x", "user": session,
                                 "messages": [{"role": "user", "content": text}]}),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            response.read()
            with guard:
                codes.append(response.status)
        except HTTPError as exc:
            with guard:
                errors.append("http %s %s" % (exc.code, exc.reason))
        except Exception as exc:  # noqa: BLE001 - the test asserts on this bucket
            with guard:
                errors.append("req %r" % exc)
        finally:
            if conn is not None:
                conn.close()

    previous = sys.getswitchinterval()
    sys.setswitchinterval(1e-4)
    threads = [threading.Thread(target=worker) for _ in range(n)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
    finally:
        sys.setswitchinterval(previous)
    for thread in threads:
        if thread.is_alive():
            with guard:
                errors.append("worker thread hung (never finished)")
    return errors, codes


def test_gateway_concurrent_requests_no_cross_loop_fail_open(tmp_path):
    """200 simultaneous requests must all succeed with context injected.

    Before the fix each request ran its own ``asyncio.run()`` loop while the
    Projector shared ``asyncio.Lock`` objects across them; under concurrency
    those locks raised "bound to a different event loop" / "attached to a
    different loop", which the gateway swallowed as fail-open (returning the
    request WITHOUT any injected context). We assert: zero request errors, zero
    fail-opens, and every forwarded body carries the injected system message
    with the routed slide and the stored memory fact.
    """
    upstream = _fake_upstream()
    config = _config()
    config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    projector = _seeded_projector(tmp_path, "load", "weather_forecast", "sunny in Porto")
    server = create_server(config, projector=projector, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]
    try:
        # Warm-up: one sequential request initialises the persistent loop, the
        # SQLite connection and the first per-session index outside the burst, so
        # cold-start cost cannot masquerade as a concurrency failure.
        warm = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
        warm.request(
            "POST", "/v1/chat/completions",
            body=json.dumps({"model": "x", "user": "load",
                             "messages": [{"role": "user", "content": "weather please"}]}),
            headers={"Content-Type": "application/json"},
        )
        warm.getresponse().read(); warm.close()
        del upstream.bodies[:]
        errors, codes = _concurrent_requests(base, 200, "load", "weather please")
        gateway = server.gateway

        assert not errors, "request errors: %s" % errors[:12]
        assert len(codes) == 200, "expected 200 responses, got %d" % len(codes)
        assert all(code == 200 for code in codes), "non-200 responses: %s" % set(codes)
        assert gateway.counters["fail_open"] == 0, "fail-opens: %d" % gateway.counters["fail_open"]
        assert len(upstream.bodies) == 200, "only %d bodies reached upstream" % len(upstream.bodies)
        for body in upstream.bodies:
            system = body["messages"][0]
            assert system["role"] == "system", "no system message injected: %r" % body["messages"][:1]
            assert "Weather slide." in system["content"], "slide not injected: %r" % system["content"][:200]
            assert "sunny in Porto" in system["content"], "memory not injected: %r" % system["content"][:200]
    finally:
        server.shutdown(); server.server_close(); server.gateway.close()
        upstream.shutdown(); upstream.server_close()


_SHUTDOWN_CHILD = '''
import json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from cyrrus.config import validate_config
from cyrrus.gateway import create_server
from cyrrus.projector import Projector


class Up(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b\'{"choices":[{"message":{"content":"ok"}}]}\')


up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
threading.Thread(target=up.serve_forever, daemon=True).start()


async def _llm(m):
    return "x"


proj = Projector({"core_lamp": {"content": "Be concise."}}, _llm,
                 memory_db_path=os.path.join(tempfile.mkdtemp(), "m.sqlite"))
cfg = validate_config({"provider": {"base_url": "http://127.0.0.1:%s/v1" % up.server_address[1], "model": "m"}})
server = create_server(cfg, projector=proj, port=0)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%s" % server.server_address[1]

for _ in range(25):
    urlopen(Request(base + "/v1/chat/completions",
                    data=json.dumps({"model": "m", "user": "s",
                                     "messages": [{"role": "user", "content": "hi"}]}).encode(),
                    headers={"Content-Type": "application/json"})).read()

server.shutdown()
server.server_close()
close = getattr(server.gateway, "close", None)
if close:
    close()
up.shutdown()
up.server_close()
print("CHILD-DONE")
'''


def test_gateway_clean_shutdown_process_exits(tmp_path):
    """A gateway process must exit with no hanging threads after shutdown.

    Runs a full create_server -> serve -> request -> shutdown cycle in a child
    interpreter. If the persistent event loop (or any loop-owned thread) is left
    non-daemon and un-stopped, the child never exits and this times out.
    """
    import subprocess
    import sys
    script = tmp_path / "shutdown_child.py"
    script.write_text(_SHUTDOWN_CHILD, encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        pytest.fail("gateway child did not exit within 90s (hanging thread)")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"CHILD-DONE" in proc.stdout, proc.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Item 1 — shutdown data loss: close() drained only a SNAPSHOT of the background
# futures, so a record_turn that raced the drain was never awaited, and one
# fired after the loop was stopped was dropped silently (record_turn is what
# extracts and stores the turn's facts, so the facts went with it).
# --------------------------------------------------------------------------- #
async def _marker_extractor(user_text):
    """Turn user text into one deterministic fact.

    The fact's value is the request's own marker string, so a fresh SQLite
    connection opened after close() proves, per session, that the turn was
    recorded and its fact extracted.
    """
    return {"turn_marker": user_text}


def _close_mid_load_burst(server, sessions, markers, close_after):
    """One request per session, all released together, gateway closed once
    ``close_after`` responses have landed.

    Returns (results, shutdown_state): results is a list of
    (session, marker, status_or_error) and shutdown_state records whether the
    closer actually ran and how many responses had arrived when close() returned.
    Closing mid-burst is the point: the handlers still between "response written"
    and "record_turn fired" are exactly the work the old shutdown dropped.
    """
    results, guard = [], threading.Lock()
    host, port = "127.0.0.1", server.server_address[1]
    barrier = threading.Barrier(len(sessions), timeout=120)
    burst_finished = threading.Event()
    shutdown_state = {"closed": False, "delivered_at_close": 0, "drain_s": None}

    def worker(index):
        session, marker = sessions[index], markers[index]
        try:
            barrier.wait()
        except threading.BrokenBarrierError as exc:
            with guard:
                results.append((session, marker, "barrier %r" % exc))
            return
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=60)
            conn.request(
                "POST", "/v1/chat/completions",
                body=json.dumps({"model": "x", "user": session,
                                 "messages": [{"role": "user", "content": marker}]}),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            response.read()
            with guard:
                results.append((session, marker, response.status))
        except Exception as exc:  # noqa: BLE001 - reported, not asserted away
            with guard:
                results.append((session, marker, "error %r" % exc))
        finally:
            if conn is not None:
                conn.close()

    def closer():
        while not burst_finished.is_set():
            with guard:
                delivered = len(results)
            if delivered >= close_after:
                break
            burst_finished.wait(0.002)
        if burst_finished.is_set() and len(results) < close_after:
            return  # the burst ended before a mid-load close was possible
        # Close the GATEWAY first, while handlers are still serving: that is the
        # race that used to drop turns. Shutting the listening socket first would
        # instead just refuse the backlog (178 of 200 connections in an earlier
        # run), so the burst would barely touch the shutdown path at all.
        drain_start = time.monotonic()
        server.gateway.close()
        with guard:
            shutdown_state["closed"] = True
            shutdown_state["delivered_at_close"] = len(results)
            shutdown_state["drain_s"] = round(time.monotonic() - drain_start, 3)
        server.shutdown()
        server.server_close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(sessions))]
    closer_thread = threading.Thread(target=closer)
    previous = sys.getswitchinterval()
    # Same stress as the concurrency test: shrink the GIL switch interval so the
    # shutdown/response interleaving actually overlaps instead of being rare.
    sys.setswitchinterval(1e-4)
    try:
        for thread in threads:
            thread.start()
        closer_thread.start()
        for thread in threads:
            thread.join(timeout=180)
        burst_finished.set()
        closer_thread.join(timeout=120)
    finally:
        sys.setswitchinterval(previous)
    for thread in threads:
        if thread.is_alive():
            results.append(("hung", "worker", "thread never finished"))
    return results, shutdown_state


def test_gateway_close_mid_load_records_every_delivered_turn(tmp_path, caplog):
    """No request that got HTTP 200 may lose its turn or its facts at shutdown.

    200 concurrent requests, one session each, close() called while the burst is
    still in flight. After close() returns, every session that received a 200
    must have (a) its turn in the projector history and (b) its marker fact in
    SQLite — read through a brand-new connection, so nothing cached is counted.
    """
    n = 200
    caplog.set_level("WARNING", logger="cyrrus.gateway")
    sessions = ["shut-%03d" % i for i in range(n)]
    markers = ["remember marker-%03d" % i for i in range(n)]

    upstream = _fake_upstream()
    config = _config()
    config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    projector = _projector(tmp_path, fact_extractor=_marker_extractor)
    server = create_server(config, projector=projector, port=0)
    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()
    try:
        results, shutdown_state = _close_mid_load_burst(server, sessions, markers,
                                                        close_after=n // 20)
        assert shutdown_state["closed"], "close() never ran during the burst"

        delivered = [(session, marker) for session, marker, status in results if status == 200]
        not_ok = [(session, status) for session, _m, status in results if status != 200]
        assert delivered, "no request returned 200: %s" % (not_ok[:8],)

        # The DB is opened only now, after close() has returned.
        connection = sqlite3.connect(str(tmp_path / "memory.sqlite"))
        try:
            stored = set(connection.execute("SELECT session_id, keyword, value FROM facts"))
        finally:
            connection.close()

        missing_facts = [(session, marker) for session, marker in delivered
                         if (session, "turn_marker", marker) not in stored]
        missing_turns = [session for session, _m in delivered
                         if len(projector._histories.get(session) or ()) != 2]

        # Diagnostic first, assertion second: shutdown behaviour is a race, so a
        # failure report has to say how much was lost and where, not just "False".
        # drain_s / refused / drain_timeout_warnings classify a failure: a loss
        # with no warning is a real bug, a loss after "drain timed out" is the
        # shutdown budget running out (slowness), which are different defects.
        warnings_text = [record.getMessage() for record in caplog.records]
        drain_timeouts = sum(1 for text in warnings_text if "drain timed out" in text)
        report = (
            "delivered=%d errors=%d close_returned_after=%d "
            "turns_lost=%d facts_lost=%d drain_s=%s refused=%d drain_timeouts=%d "
            "lost_samples=%s"
            % (len(delivered), len(not_ok), shutdown_state["delivered_at_close"],
               len(missing_turns), len(missing_facts), shutdown_state["drain_s"],
               server.gateway.counters.get("record_refused", -1), drain_timeouts,
               missing_turns[:6])
        )
        print("SHUTDOWN-LOSS " + report)

        assert not missing_turns, "turn(s) lost at shutdown (report=%s)" % report
        assert not missing_facts, "fact(s) lost at shutdown (report=%s)" % report
        assert len(stored) == len(delivered), (
            "stored %d facts for %d delivered requests" % (len(stored), len(delivered)))
    finally:
        server.shutdown(); server.server_close(); server.gateway.close()
        upstream.shutdown(); upstream.server_close()


_CLOSE_MID_LOAD_CHILD = '''
import http.client, json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from cyrrus.config import validate_config
from cyrrus.gateway import create_server
from cyrrus.projector import Projector


class Up(BaseHTTPRequestHandler):
    daemon_threads = True
    request_queue_size = 512

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers["Content-Length"])
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b\'{"choices":[{"message":{"content":"ok"}}]}\')


up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
threading.Thread(target=up.serve_forever, daemon=True).start()


async def _llm(m):
    return "x"


async def _extract(text):
    return {"turn_marker": text}


proj = Projector({"core_lamp": {"content": "Be concise."}}, _llm,
                 memory_db_path=os.path.join(tempfile.mkdtemp(), "m.sqlite"),
                 fact_extractor=_extract)
cfg = validate_config({"provider": {"base_url": "http://127.0.0.1:%s/v1" % up.server_address[1], "model": "m"}})
server = create_server(cfg, projector=proj, port=0)
threading.Thread(target=server.serve_forever, daemon=True).start()
host, port = "127.0.0.1", server.server_address[1]

done = []
guard = threading.Lock()
burst_over = threading.Event()


def worker(i):
    conn = None
    try:
        conn = http.client.HTTPConnection(host, port, timeout=30)
        conn.request("POST", "/v1/chat/completions",
                     body=json.dumps({"model": "m", "user": "s%03d" % i,
                                      "messages": [{"role": "user", "content": "remember marker-%03d" % i}]}),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse(); r.read()
        with guard:
            done.append(r.status)
    except Exception as e:
        with guard:
            done.append(repr(e))
    finally:
        if conn:
            conn.close()


threads = [threading.Thread(target=worker, args=(i,)) for i in range(60)]
for t in threads:
    t.start()

while len(done) < 8:
    if burst_over.wait(0.005):
        break

# Same order the burst test uses: gateway first, so the drain races live
# handlers, then the listener.
close = getattr(server.gateway, "close", None)
if close:
    close()
server.shutdown()
server.server_close()

burst_over.set()
for t in threads:
    t.join(120)

up.shutdown()
up.server_close()
leftover = [t.name for t in threading.enumerate()
            if t is not threading.main_thread() and not t.daemon and t.is_alive()]
loop_thread = getattr(server.gateway, "_loop_thread", None)
print("NONDAEMON=%s" % leftover)
print("LOOP_ALIVE=%s" % bool(loop_thread and loop_thread.is_alive()))
print("CHILD-DONE")
'''


def test_gateway_close_mid_load_child_exits_cleanly():
    """Closing while traffic is in flight must still leave nothing hanging.

    The drain makes close() wait for handlers, so it is the path most likely to
    strand the loop thread or a non-daemon thread and wedge interpreter exit.
    """
    import subprocess
    proc = subprocess.run([sys.executable, "-c", _CLOSE_MID_LOAD_CHILD],
                          capture_output=True, timeout=180)
    out = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-3000:]
    assert "CHILD-DONE" in out, out
    assert "NONDAEMON=[]" in out, "non-daemon threads left behind: %s" % out
    assert "LOOP_ALIVE=False" in out, "event loop thread still alive: %s" % out


def test_gateway_close_with_stalled_upstream_returns_and_speaks_up(tmp_path, caplog):
    """A handler wedged on a slow upstream must not wedge close().

    The drain waits for open turn windows, so an upstream that stops sending
    mid-stream can only be ended by the budget.  close() has to return when the
    budget runs out, say so unambiguously — including how many served turns will
    not be recorded — and the stalled requests must then still complete instead
    of deadlocking.
    """
    caplog.set_level("WARNING", logger="cyrrus.gateway")
    upstream = _fake_upstream()
    config = _config()
    config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    server, base = _start(config, _projector(tmp_path))
    upstream.stream_gate = threading.Event()   # stalls after the first SSE chunk
    outcomes, guard = [], threading.Lock()

    def client():
        try:
            response = _request(base, {"model": "x", "stream": True,
                                       "messages": [{"role": "user", "content": "go"}]})
            body = response.read()             # blocks until the upstream resumes
            with guard:
                outcomes.append((response.status, len(body)))
        except Exception as exc:  # noqa: BLE001 - reported through the assertion
            with guard:
                outcomes.append(repr(exc))

    threads = [threading.Thread(target=client, daemon=True) for _ in range(5)]
    for thread in threads:
        thread.start()
    assert upstream.first_sent.wait(10), "upstream never sent a first chunk"
    time.sleep(0.2)  # let the other handlers reach the same stall

    budget = 1.0
    started = time.monotonic()
    server.gateway.close(timeout=budget)
    elapsed = time.monotonic() - started
    assert elapsed < budget + 10.0, "close() did not return: deadlock (%.1fs)" % elapsed
    assert elapsed >= budget, "close() returned before using the drain budget"

    warnings = [r.getMessage() for r in caplog.records]
    timed_out = [w for w in warnings if "drain timed out" in w]
    assert timed_out, "stalled drain ended without a warning: %s" % warnings
    assert "will not be recorded" in timed_out[0], timed_out[0]
    assert server.gateway._loop_thread is None, "loop thread kept after close()"

    upstream.stream_gate.set()  # the stalled requests must now finish on their own
    for thread in threads:
        thread.join(30)
    assert not any(t.is_alive() for t in threads), "request thread stuck after close()"
    assert len(outcomes) == 5, outcomes
    assert all(isinstance(o, tuple) and o[0] == 200 and o[1] > 0 for o in outcomes), outcomes
    server.gateway.close()  # idempotent
    upstream.shutdown(); upstream.server_close()


def test_gateway_close_with_failing_extractor_drains_fast_and_cleanly(tmp_path, caplog):
    """A broken extractor must not turn shutdown into a hang or a silent loss.

    record_turn swallows extractor failures and falls back to the built-in
    facts, so every background future still resolves: the drain must finish on
    its first pass — well inside the budget, with no timeout warning — and the
    turn itself must survive in history.
    """
    caplog.set_level("WARNING", logger="cyrrus.projector")
    caplog.set_level("WARNING", logger="cyrrus.gateway")
    failures = []

    def exploding_extractor(user_text):
        failures.append(user_text)
        raise RuntimeError("extractor exploded")

    upstream = _fake_upstream()
    config = _config()
    config["provider"]["base_url"] = "http://127.0.0.1:%s/v1" % upstream.server_address[1]
    projector = _projector(tmp_path, fact_extractor=exploding_extractor)
    server, base = _start(config, projector)
    try:
        n = 20
        statuses = []
        status_guard = threading.Lock()

        def client(i):
            try:
                statuses.append(_request(base, {"model": "x", "user": "boom-%03d" % i,
                                                "messages": [{"role": "user",
                                                              "content": "remember %d" % i}]}).status)
            except Exception as exc:  # noqa: BLE001
                with status_guard:
                    statuses.append(repr(exc))

        threads = [threading.Thread(target=client, args=(i,)) for i in range(n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        assert not any(t.is_alive() for t in threads), "request thread hung"
        assert len(statuses) == n and all(s == 200 for s in statuses), statuses
        assert failures, "extractor never ran"

        started = time.monotonic()
        server.gateway.close()
        drain_s = round(time.monotonic() - started, 3)
        warnings = [r.getMessage() for r in caplog.records]
        print("EXTRACTOR-FAIL-DRAIN drain_s=%s timeouts=%d extractor_warnings=%d"
              % (drain_s, sum(1 for w in warnings if "drain timed out" in w),
                 sum(1 for w in warnings if "extractor failed" in w)))
        assert drain_s < 5.0, "failing extractor made the drain slow: %ss" % drain_s
        assert not [w for w in warnings if "drain timed out" in w], warnings
        assert sum(1 for w in warnings if "extractor failed" in w) >= 1, warnings
        assert server.gateway.counters.get("record_refused", 0) == 0
        recorded = [s for s in ("boom-%03d" % i for i in range(n))
                    if len(projector._histories.get(s) or ()) == 2]
        assert len(recorded) == n, "turn(s) lost with a failing extractor: %s" % recorded
    finally:
        server.shutdown(); server.server_close(); server.gateway.close()
        upstream.shutdown(); upstream.server_close()


