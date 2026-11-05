"""Local OpenAI-compatible reverse proxy that injects Cyrrus context.

The gateway intentionally uses only the standard library so it can be used in
the base installation.  It is a proxy, not a chat UI.
"""
import asyncio
import copy
import json
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .config import load_dotenv
from .projector import Projector

log = logging.getLogger(__name__)
MAX_BODY = 10 * 1024 * 1024


def _is_loopback(host):
    return host in ("127.0.0.1", "::1", "localhost")


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    return ""


def _last_user(messages):
    for message in reversed(messages):
        if message.get("role") == "user":
            return _text(message.get("content", ""))
    return ""


def _safe_trace(trace):
    """Keep decision metadata, never request or context text by default."""
    return {
        "session": trace.get("session_id"),
        "routed": trace.get("routed", []),
        "ghosts": trace.get("ghosts", []),
        "fact_keys": [item.get("key") for item in trace.get("facts", [])],
        "dropped": trace.get("dropped", []),
        "stats": trace.get("stats", {}),
    }


class Gateway:
    """State and request handling for :class:`ThreadingHTTPServer`."""

    def __init__(self, config, projector=None, log_prompts=False):
        self.config = config
        self.options = config["gateway"]
        self.log_prompts = log_prompts
        self.dotenv = load_dotenv()
        self.lock = threading.Lock()
        self.traces = deque(maxlen=50)
        self.counters = {"requests": 0, "injected": 0, "skipped": 0, "fail_open": 0}
        self.projector = projector or self._make_projector()
        self.warmup_thread = None
        self._start_warmup()

    def _start_warmup(self):
        """Optionally warm retrieval indexes for the most-recently-used
        sessions on a background daemon thread.

        Gated by ``memory.warmup_sessions`` (0 = disabled, the default). Never
        blocks startup or request handling: the thread is a daemon, does its
        own bounded work under the backend's connection lock, and swallows any
        error. Silently skipped for backends without warm-up support.
        """
        try:
            count = int(self.config.get("memory", {}).get("warmup_sessions", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            return
        backend = getattr(getattr(self.projector, "memory", None), "_backend", None)
        if backend is None or not hasattr(backend, "warm_recent_sync"):
            return

        def _run():
            try:
                warmed = backend.warm_recent_sync(count)
                log.info("Cyrrus warm-up pre-built %d session index(es).", warmed)
            except Exception as exc:
                log.debug("gateway warm-up skipped: %s", exc)

        self.warmup_thread = threading.Thread(
            target=_run, name="cyrrus-warmup", daemon=True
        )
        self.warmup_thread.start()

    def _make_projector(self):
        import pathlib
        slides_path = pathlib.Path(self.config.get("context", {}).get("slides_path", "slides.json"))
        if slides_path.exists():
            with open(slides_path, "r", encoding="utf-8") as handle:
                slides = json.load(handle)
        else:
            slides = {"core_lamp": {"content": "You are a helpful assistant."}}

        async def unused_llm(messages):
            raise RuntimeError("gateway context builder does not call an LLM")

        memory = self.config.get("memory", {})
        context = self.config.get("context", {})
        return Projector(
            slides, unused_llm, max_context_tokens=context.get("max_context_tokens", 4000),
            memory_db_path=memory.get("db_path"),
            max_memory_facts=memory.get("max_facts_per_session", 50),
        )

    def _secret(self, env_name):
        return os.environ.get(env_name) or self.dotenv.get(env_name)

    def authorize(self, headers):
        env_name = self.options.get("api_key_env")
        if not env_name:
            return True
        expected = self._secret(env_name)
        supplied = headers.get("Authorization", "")
        return bool(expected and supplied == "Bearer " + expected)

    def session_for(self, headers, payload):
        return headers.get("X-Cyrrus-Session") or payload.get("user") or self.options["session"]

    def prepare(self, payload, headers):
        """Return (payload, session, user_text, trace), preserving tool traffic."""
        original = copy.deepcopy(payload)
        messages = payload.get("messages", [])
        session = self.session_for(headers, payload)
        user_text = _last_user(messages)
        has_tools = bool(payload.get("tools")) or any(m.get("role") == "tool" for m in messages)
        if headers.get("X-Cyrrus-Skip") == "1":
            self.counters["skipped"] += 1
            return original, session, user_text, {"skipped": True}
        try:
            context, trace = asyncio.run(self.projector.build_context(user_text, session))
            result = copy.deepcopy(payload)
            if not has_tools:
                result["messages"] = self._inject(messages, context)
                if self.options.get("mode") == "manage":
                    result["messages"] = self._compact(result["messages"])
            self.counters["injected"] += 1
            return result, session, user_text, trace
        except Exception as exc:
            if not self.options.get("fail_open", True):
                raise
            log.warning("Cyrrus context failed open: %s", exc)
            self.counters["fail_open"] += 1
            return original, session, user_text, {"fail_open": True, "error": type(exc).__name__}

    def _inject(self, messages, context):
        result = copy.deepcopy(messages)
        for message in result:
            if message.get("role") == "system":
                old = _text(message.get("content", ""))
                message["content"] = old + "\n\n" + context if old else context
                return result
        return [{"role": "system", "content": context}] + result

    def _compact(self, messages):
        """Fit client history while retaining system messages and latest turns.

        Context construction remains separate from compaction.  Tool traffic
        never reaches this method (``prepare`` deliberately treats it as
        inject-only), so removing old conversational messages cannot alter an
        agent protocol exchange.  The projector's tokenizer budgets the result
        and its optional summarizer hook condenses the removed turns.
        """
        budget = self.config.get("context", {}).get("max_context_tokens", 4000)
        result = list(messages)

        def size():
            return sum(self.projector._estimate_tokens(_text(m.get("content", ""))) for m in result)

        # Always protect the newest user/assistant exchange where possible.
        non_system = [i for i, item in enumerate(result) if item.get("role") != "system"]
        protected = set(non_system[-2:])
        dropped = []
        while size() > budget:
            index = next((i for i, item in enumerate(result)
                          if item.get("role") != "system" and i not in protected), None)
            if index is None:
                break
            dropped.append(result.pop(index))
            protected = {i - 1 if i > index else i for i in protected}

        summary = self._summarize(dropped)
        if summary:
            insert_at = 0
            while insert_at < len(result) and result[insert_at].get("role") == "system":
                insert_at += 1
            result.insert(insert_at, {"role": "system", "content": summary})
        return result

    def _summarize(self, dropped):
        summarizer = getattr(self.projector, "history_summarizer", None)
        if not summarizer or not dropped:
            return None
        try:
            from .projector import _run_history_summarizer
            summary = asyncio.run(_run_history_summarizer(
                summarizer, dropped, getattr(self.projector, "summarizer_timeout", 10.0)
            ))
        except Exception as exc:
            log.warning("Cyrrus manage-mode summarizer failed: %s", exc)
            return None
        return summary.strip() if isinstance(summary, str) and summary.strip() else None

    def upstream_url(self, suffix):
        base = self.config.get("provider", {}).get("base_url")
        if not base:
            raise ValueError("No provider.base_url configured for gateway")
        return urljoin(base.rstrip("/") + "/", suffix.lstrip("/"))

    def forward(self, path, body=None, headers=None):
        headers = headers or {}
        provider = self.config.get("provider", {})
        key_env = provider.get("api_key_env")
        upstream_headers = {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length", "authorization", "x-cyrrus-session", "x-cyrrus-skip")}
        upstream_headers["Content-Type"] = "application/json"
        if key_env and self._secret(key_env):
            upstream_headers["Authorization"] = "Bearer " + self._secret(key_env)
        request = Request(self.upstream_url(path), data=body, headers=upstream_headers, method="POST" if body is not None else "GET")
        return urlopen(request, timeout=self.options["upstream_timeout"])

    def add_trace(self, session, trace, started):
        item = _safe_trace(trace)
        item["timing_ms"] = int((time.time() - started) * 1000)
        if self.log_prompts:
            item["context"] = trace.get("system_message", "")
        with self.lock:
            self.traces.append(item)


def make_handler(gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CyrrusGateway/1.0"

        def log_message(self, fmt, *args):
            log.info("gateway %s", fmt % args)

        def _json(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def _auth(self):
            if gateway.authorize(self.headers):
                return True
            self._json(401, {"error": {"message": "Unauthorized", "type": "authentication_error"}})
            return False

        def do_GET(self):
            if not self._auth(): return
            if self.path == "/health":
                return self._json(200, {"status": "ok"})
            if self.path == "/cyrrus/status":
                return self._json(200, {"gateway": {k: v for k, v in gateway.options.items() if k != "api_key_env"}, "counters": gateway.counters})
            if self.path == "/cyrrus/last":
                return self._json(200, {"requests": list(gateway.traces)})
            if self.path == "/v1/models":
                try:
                    response = gateway.forward("models", headers=dict(self.headers)); data = response.read(); self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json")); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
                except Exception:
                    model = gateway.config.get("provider", {}).get("model") or "cyrrus"
                    self._json(200, {"object": "list", "data": [{"id": model, "object": "model"}, {"id": "cyrrus", "object": "model"}]})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth(): return
            if self.path != "/v1/chat/completions": return self._json(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                # Drain the rejected body before responding. Closing a socket
                # with unread request data sends a TCP RST, which can abort
                # the client's read of the 413 (WinError 10053 on Windows).
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                return self._json(413, {"error": "request body exceeds 10 MB"})
            try: payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError): return self._json(400, {"error": "invalid JSON"})
            started = time.time(); gateway.counters["requests"] += 1
            try:
                outgoing, session, user_text, trace = gateway.prepare(payload, self.headers)
                forced = gateway.options.get("force_model")
                if forced: outgoing["model"] = forced
                elif not outgoing.get("model") or outgoing.get("model") == "cyrrus": outgoing["model"] = gateway.config.get("provider", {}).get("model")
                raw = json.dumps(outgoing).encode("utf-8")
                try: response = gateway.forward("chat/completions", raw, dict(self.headers))
                except HTTPError as exc: response = exc
                self.send_response(response.code if isinstance(response, HTTPError) else response.status)
                for key in ("Content-Type", "Cache-Control"):
                    if response.headers.get(key): self.send_header(key, response.headers[key])
                self.end_headers()
                chunks = []; streaming = bool(payload.get("stream"))
                while True:
                    if not streaming:
                        data = response.read()
                    elif hasattr(response, "read1"):
                        data = response.read1(4096)
                    else:
                        data = response.read(4096)
                    if not data: break
                    chunks.append(data); self.wfile.write(data); self.wfile.flush()
                    if not streaming: break
                assistant = ""
                try:
                    decoded = b"".join(chunks).decode("utf-8")
                    if streaming:
                        for line in decoded.splitlines():
                            if line.startswith("data: ") and line[6:] != "[DONE]": assistant += json.loads(line[6:])["choices"][0].get("delta", {}).get("content", "")
                    else: assistant = json.loads(decoded)["choices"][0]["message"].get("content", "")
                except Exception: pass
                if not payload.get("tools") and not any(m.get("role") == "tool" for m in payload.get("messages", [])):
                    threading.Thread(target=lambda: asyncio.run(gateway.projector.record_turn(session, user_text, assistant)), daemon=True).start()
                gateway.add_trace(session, trace, started)
            except (URLError, ValueError) as exc:
                self._json(502, {"error": {"message": str(exc), "type": "upstream_error"}})
    return Handler


def create_server(config, projector=None, host=None, port=None, log_prompts=False):
    options = config["gateway"]
    host = host or options["host"]; port = options["port"] if port is None else port
    if not _is_loopback(host) and not options.get("api_key_env"):
        raise ValueError("Non-loopback gateway binding requires gateway.api_key_env")
    gateway = Gateway(config, projector=projector, log_prompts=log_prompts)
    while True:
        try:
            server = ThreadingHTTPServer((host, port), make_handler(gateway)); server.gateway = gateway; return server
        except OSError:
            if port == 0: raise
            port += 1


def serve(config, host=None, port=None, log_prompts=False):
    server = create_server(config, host=host, port=port, log_prompts=log_prompts)
    print("Cyrrus gateway: http://%s:%s/v1  model=%s  mode=%s" % (server.server_address[0], server.server_address[1], config.get("provider", {}).get("model") or "(unset)", config["gateway"]["mode"]))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
