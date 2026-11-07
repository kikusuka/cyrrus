"""Item 1 follow-up (a): ``cyrrus serve`` and Ctrl+C.

The first Ctrl+C must announce the drain instead of dropping pending turns
quietly; the second must quit immediately and print how many served turns were
not recorded.  Tested in a child process, because the signals have to reach a
main thread that is blocked inside serve()/close().
"""
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time

import pytest

from cyrrus.config import validate_config
from cyrrus.gateway import Gateway, drain_notice, forced_quit
from cyrrus.projector import Projector


async def _llm(messages):
    return "unused"


def _config():
    return validate_config({"provider": {"base_url": "http://127.0.0.1:9/v1",
                                         "model": "test-model"}})

_CHILD_A = r'''
import json, os, socket, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen
from cyrrus.config import validate_config
from cyrrus.gateway import serve
from cyrrus.projector import Projector


class Up(BaseHTTPRequestHandler):
    daemon_threads = True
    request_queue_size = 128

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers["Content-Length"]); self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')


up = ThreadingHTTPServer(("127.0.0.1", 0), Up)
threading.Thread(target=up.serve_forever, daemon=True).start()


async def _llm(m):
    return "x"


def slow(text):
    time.sleep(120)
    return {"turn_marker": text}
'''

_CHILD_B = r'''

proj = Projector({"core_lamp": {"content": "Be concise."}}, _llm,
                 memory_db_path=os.path.join(tempfile.mkdtemp(), "m.sqlite"),
                 fact_extractor=slow, extractor_timeout=120.0)
sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
cfg = validate_config({"provider": {"base_url": "http://127.0.0.1:%d/v1" % up.server_address[1],
                                    "model": "m"}})
ok = []
N = 6


def worker(i):
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = urlopen(Request("http://127.0.0.1:%d/v1/chat/completions" % port,
                                data=json.dumps({"model": "m", "user": "sig-%02d" % i,
                                                 "messages": [{"role": "user",
                                                               "content": "remember %02d" % i}]})
                                .encode(),
                                headers={"Content-Type": "application/json"}), timeout=30)
            r.read(); ok.append(r.status)
        except URLError:
            time.sleep(0.05); continue
        except Exception as e:
            ok.append(repr(e))
        break
    if len(ok) == N:
        print("BURST-OK", flush=True)


for i in range(N):
    threading.Thread(target=worker, args=(i,), daemon=True).start()
serve(cfg, projector=proj, host="127.0.0.1", port=port)
print("SERVE-RETURNED", flush=True)
'''

_CHILD = _CHILD_A + _CHILD_B

_PROBE = '\nimport time\nprint("PROBE-READY", flush=True)\n' \
         'try:\n    time.sleep(30)\nexcept KeyboardInterrupt:\n' \
         '    print("PROBE-GOT-SIGNAL", flush=True)\n'


def _lines(proc):
    sink = queue.Queue()

    def pump():
        for line in proc.stdout:
            sink.put(line.rstrip())
        sink.put(None)
    threading.Thread(target=pump, daemon=True).start()
    return sink


def _send_ctrl_c(proc):
    if os.name == "nt":
        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)


def _wait(sink, pattern, timeout=25.0):
    compiled = re.compile(pattern)
    seen = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = sink.get(max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            break
        if line is None:
            break
        seen.append(line)
        if compiled.search(line):
            return line, seen
    raise AssertionError("no line matched %r; seen=%s" % (pattern, seen[-25:]))


def _spawn(script):
    flags = 0 if os.name != "nt" else subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([sys.executable, "-u", "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, creationflags=flags)


def _signals_reach_a_child():
    proc = _spawn(_PROBE)
    try:
        _wait(_lines(proc), "PROBE-READY", timeout=30)
        _send_ctrl_c(proc)
        _wait(_lines(proc), "PROBE-GOT-SIGNAL", timeout=10)
        return True
    except (AssertionError, OSError, ValueError, NotImplementedError):
        return False
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=10)


def test_serve_ctrl_c_drains_then_force_quits():
    """Ctrl+C #1 announces the drain, Ctrl+C #2 quits at once with a loss count."""
    if not _signals_reach_a_child():
        pytest.skip("this platform cannot deliver SIGINT/CTRL_BREAK to a child "
                    "process (Windows console signals need a real console); the "
                    "drain itself is covered by test_gateway_close_mid_load_*")
    proc = _spawn(_CHILD)
    sink = _lines(proc)
    try:
        _wait(sink, r"Cyrrus gateway:", timeout=60)
        _wait(sink, "BURST-OK", timeout=60)
        _send_ctrl_c(proc)
        announced, _seen = _wait(sink, r"draining \d+ pending turns.*force quit")
        pending = int(re.search(r"draining (\d+) pending turns", announced).group(1))
        assert pending > 0, announced
        _send_ctrl_c(proc)
        forced, _seen = _wait(sink, r"FORCED QUIT")
        assert proc.wait(timeout=20) == 1, "forced quit did not exit immediately"
        lost = re.search(r"(\d+) served turn\(s\) not recorded", forced)
        assert lost, forced
        assert int(lost.group(1)) == pending, "%s vs %s" % (forced, announced)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=20)


def test_announce_and_forced_quit_add_up_without_a_real_signal(tmp_path, capsys):
    """Both Ctrl+C messages must account for every pending turn.

    Windows cannot deliver a console signal to a console-less child (hence the
    skip above), so the same two lines are checked directly against a gateway
    whose record_turn work is held pending: no timing budget, no race, just the
    arithmetic the operator is shown.
    """
    gate = threading.Event()
    k = 4

    def blocking(text):
        gate.wait(60)
        return {"turn_marker": text}

    projector = Projector({"core_lamp": {"content": "c"}}, _llm,
                          memory_db_path=str(tmp_path / "m.sqlite"),
                          fact_extractor=blocking, extractor_timeout=60.0)
    gateway = Gateway(_config(), projector=projector)
    try:
        for i in range(k):
            gateway._fire(projector.record_turn("sig-%02d" % i, "remember %02d" % i, "ok"))
        deadline = time.monotonic() + 30
        while gateway.pending_turns() < k and time.monotonic() < deadline:
            time.sleep(0.02)
        assert gateway.pending_turns() == k, gateway.shutdown_counts()

        assert drain_notice(gateway) == k
        out = capsys.readouterr().out
        assert "draining %d pending turns" % k in out, out
        assert "press Ctrl+C again to force quit" in out, out

        codes = []
        forced_quit(gateway, _exit=codes.append)
        text = capsys.readouterr().out
        assert "FORCED QUIT" in text, text
        assert "%d record_turn task(s) still queued" % k in text, text
        assert "at least %d served turn(s) will not be recorded" % k in text, text
        assert codes == [1], codes
        assert gateway.shutdown_counts() == (k, 0, 0)
    finally:
        gate.set()
        gateway.close()


def test_serve_routes_the_two_ctrl_c_signals_to_differently(tmp_path, monkeypatch, capsys):
    """serve(): Ctrl+C #1 drains, Ctrl+C #2 forces the quit with a loss count.

    The subprocess test above covers real signals where the platform allows them;
    this covers serve()'s own branching everywhere, by making the first
    serve_forever() raise KeyboardInterrupt and the drain raise it again.
    """
    import cyrrus.gateway as gateway_module
    gate = threading.Event()
    k = 3

    def blocking(text):
        gate.wait(60)
        return {"turn_marker": text}

    projector = Projector({"core_lamp": {"content": "c"}}, _llm,
                          memory_db_path=str(tmp_path / "m.sqlite"),
                          fact_extractor=blocking, extractor_timeout=60.0)
    gateway = Gateway(_config(), projector=projector)
    fake_calls = []

    class _Server:
        server_address = ("127.0.0.1", 1)

        def __init__(self, gateway):
            self.gateway = gateway

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            fake_calls.append("server_close")

    def fake_close(*args, **kwargs):
        raise KeyboardInterrupt

    def record_forced_quit(gw, **kwargs):
        fake_calls.append(gw.pending_turns())

    for i in range(k):
        gateway._fire(projector.record_turn("route-%02d" % i, "remember %02d" % i, "ok"))
    deadline = time.monotonic() + 30
    while gateway.pending_turns() < k and time.monotonic() < deadline:
        time.sleep(0.02)
    monkeypatch.setattr(gateway_module, "create_server", lambda *a, **kw: _Server(gateway))
    monkeypatch.setattr(gateway, "close", fake_close)
    monkeypatch.setattr(gateway_module, "forced_quit", record_forced_quit)
    try:
        gateway_module.serve(_config())
        out = capsys.readouterr().out
        assert "draining %d pending turns" % k in out, out
        assert fake_calls == ["server_close", k], fake_calls
    finally:
        gate.set()
        Gateway.close(gateway)


