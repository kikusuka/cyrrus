"""Smoke-test a built cyrrus binary.

Checks ``--version``, ``doctor`` and a real start/stop of ``cyrrus serve``
against a local fake OpenAI-compatible upstream.  Uses only the standard
library, so it also runs on the GitHub runners before/after PyInstaller.

    python packaging/smoke_test.py --binary dist/cyrrus
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            self._send({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)
        if self.path.rstrip("/") in ("/v1/chat/completions", "/chat/completions"):
            self._send({
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 0,
                "model": "fake-model",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "fake reply"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
            return
        self.send_error(404)


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def run_checked(binary: Path, args, cwd: Path, timeout: float) -> str:
    result = subprocess.run(
        [str(binary)] + list(args),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = (result.stdout or "") + (result.stderr or "")
    print("$ %s %s" % (binary.name, " ".join(args)))
    print(output.rstrip())
    if result.returncode != 0:
        raise RuntimeError("command failed with exit code %d" % result.returncode)
    return output


def write_config(tmp: Path, upstream_port: int, gateway_port: int) -> None:
    config = {
        "schema_version": 1,
        "provider": {
            "service": "custom",
            "base_url": "http://127.0.0.1:%d/v1" % upstream_port,
            "model": "fake-model",
            "api_key_env": None,
        },
        "memory": {
            "db_path": str(tmp / "cyrrus.db"),
            "retrieval": "keyword",
            "max_facts_per_session": 10,
            "embedding_min_score": 0.7,
            "trace_values": False,
        },
        "context": {
            "renderer": "default",
            "max_context_tokens": 1000,
            "slides_path": str(tmp / "slides.json"),
        },
        "ui": {"animation": "off", "onboarded": True},
        "gateway": {
            "host": "127.0.0.1",
            "port": gateway_port,
            "mode": "inject",
            "session": "smoke",
            "fail_open": True,
            "force_model": None,
            "api_key_env": None,
            "upstream_timeout": 10.0,
        },
    }
    (tmp / "cyrrus.config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    slides = {
        "core_lamp": {
            "content": "You are a helpful assistant.",
            "tokens": 10,
            "priority": 5,
        }
    }
    (tmp / "slides.json").write_text(json.dumps(slides, indent=2) + "\n", encoding="utf-8")


def smoke_serve(binary: Path, tmp: Path, timeout: float) -> None:
    upstream_port = free_port()
    gateway_port = free_port()
    upstream = ThreadingHTTPServer(("127.0.0.1", upstream_port), FakeUpstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    write_config(tmp, upstream_port, gateway_port)

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen(
        [str(binary), "serve"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    health_url = "http://127.0.0.1:%d/health" % gateway_port
    base_url = "http://127.0.0.1:%d/v1" % gateway_port
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError("serve exited before health check:\n%s" % output)
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.25)
        else:
            raise RuntimeError("serve did not become healthy within %.0fs" % timeout)

        print("$ %s serve (health) -> %s" % (binary.name, health_url))
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps({
                "model": "fake-model",
                "messages": [{"role": "user", "content": "hello from the smoke test"}],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        reply = payload["choices"][0]["message"]["content"]
        if reply != "fake reply":
            raise RuntimeError("unexpected upstream reply: %r" % reply)
        print("$ %s serve (chat) -> %s" % (binary.name, reply))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        upstream.shutdown()
        upstream.server_close()
        print("$ %s serve stopped" % binary.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, help="path to the built cyrrus binary")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for the gateway")
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    if not binary.is_file():
        print("ERROR: binary not found: %s" % binary, file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="cyrrus-smoke-"))
    try:
        version = run_checked(binary, ["--version"], tmp, timeout=60)
        if "cyrrus" not in version.lower():
            raise RuntimeError("--version did not mention cyrrus")
        doctor = run_checked(binary, ["doctor"], tmp, timeout=120)
        if "Overall status:" not in doctor:
            raise RuntimeError("doctor did not print an overall status")
        smoke_serve(binary, tmp, args.timeout)
    finally:
        # On Windows SQLite can keep the database handle briefly after the
        # gateway process exits; retry so the temp directory still cleans up.
        for _ in range(20):
            try:
                shutil.rmtree(tmp)
                break
            except OSError:
                time.sleep(0.25)
    print("SMOKE TEST PASSED: %s" % binary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CI needs a readable failure
        print("SMOKE TEST FAILED: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
