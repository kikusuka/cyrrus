"""
Tests for the OpenAI-compatible provider (stdlib urllib, no new deps).

A fake HTTP server on a random local port serves both a normal JSON
response and an SSE streaming response. Covers: normal call, streaming,
Authorization header only when an api_key is given, non-200 errors with
the status included, and timeout.
"""
import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cyrrus import openai_compatible
from cyrrus.providers import StreamChunk


def _start_server(mode: str = "normal"):
    """
    Start a fake OpenAI-compatible chat/completions server on a random port.
    Returns (server, port). The server records the last request's auth
    header, body and path in server.last_auth / server.last_body / server.last_path.
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            self.server.last_body = body
            self.server.last_auth = self.headers.get("Authorization")
            self.server.last_path = self.path

            if self.path != "/chat/completions":
                self.send_response(404)
                self.end_headers()
                return

            if mode == "error":
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"server boom"}')
                return

            if mode == "slow":
                time.sleep(10)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"never"}}]}')
                return

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            stream = bool(payload.get("stream", False))

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                frames = []
                for content in ("Hello ", "world", "!"):
                    frames.append(
                        "data: "
                        + json.dumps({"choices": [{"delta": {"content": content}}]})
                        + "\n"
                    )
                # A role-only delta (empty content) that must be skipped.
                frames.append(
                    "data: "
                    + json.dumps({"choices": [{"delta": {"role": "assistant"}}]})
                    + "\n"
                )
                frames.append("data: [DONE]\n")
                self.wfile.write("".join(frames).encode("utf-8"))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    b'{"choices":[{"message":{"content":"hello assistant"}}]}'
                )

        def log_message(self, *args):
            pass  # keep test output quiet

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.mode = mode
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_normal_call_returns_message_content():
    server, port = _start_server("normal")
    try:
        llm = openai_compatible(base_url=_base_url(port), model="m")
        result = await llm([{"role": "user", "content": "hi"}])
        assert result == "hello assistant"
        payload = json.loads(server.last_body)
        assert payload["model"] == "m"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["stream"] is False
        assert server.last_auth is None
        assert server.last_path == "/chat/completions"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_endpoint_used_as_is_when_already_chat_completions():
    server, port = _start_server("normal")
    try:
        llm = openai_compatible(
            base_url=_base_url(port) + "/chat/completions/", model="m"
        )
        await llm([{"role": "user", "content": "hi"}])
        assert server.last_path == "/chat/completions"
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_streaming_yields_non_empty_deltas():
    server, port = _start_server("normal")
    try:
        llm = openai_compatible(base_url=_base_url(port), model="m")
        texts = []
        async for chunk in llm.astream([{"role": "user", "content": "hi"}]):
            assert isinstance(chunk, StreamChunk)
            if chunk.text:
                texts.append(chunk.text)
        assert texts == ["Hello ", "world", "!"]
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_authorization_header_only_with_api_key():
    server, port = _start_server("normal")
    try:
        llm = openai_compatible(
            base_url=_base_url(port), model="m", api_key="sk-test123"
        )
        await llm([{"role": "user", "content": "hi"}])
        assert server.last_auth == "Bearer sk-test123"
    finally:
        server.shutdown()

    server2, port2 = _start_server("normal")
    try:
        llm2 = openai_compatible(base_url=_base_url(port2), model="m")
        await llm2([{"role": "user", "content": "hi"}])
        assert server2.last_auth is None
    finally:
        server2.shutdown()


@pytest.mark.asyncio
async def test_non_200_error_includes_http_status():
    server, port = _start_server("error")
    try:
        llm = openai_compatible(base_url=_base_url(port), model="m")
        with pytest.raises(RuntimeError) as excinfo:
            await llm([{"role": "user", "content": "hi"}])
        assert "500" in str(excinfo.value)
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_timeout_is_respected():
    server, port = _start_server("slow")
    try:
        llm = openai_compatible(
            base_url=_base_url(port), model="m", timeout=0.2
        )
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(
                llm([{"role": "user", "content": "hi"}]), timeout=5
            )
    finally:
        server.shutdown()
