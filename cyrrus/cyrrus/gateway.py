"""Local OpenAI-compatible reverse proxy that injects Cyrrus context.

The gateway intentionally uses only the standard library so it can be used in
the base installation.  It is a proxy, not a chat UI.
"""
import asyncio
import concurrent.futures
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


class _GatewayServer(ThreadingHTTPServer):
    """Threaded HTTP server sized for concurrent proxying.

    ``daemon_threads`` lets in-flight handler threads never block interpreter
    exit; the raised listen backlog (the stdlib default is only 5) keeps the
    accept queue from refusing legitimate concurrent clients.  Handler threads
    only read/write sockets and forward — the actual asyncio work is serialised
    onto the Gateway's single event loop — so a larger backlog cannot reintroduce
    cross-loop sharing.
    """
    daemon_threads = True
    request_queue_size = 512


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
        # Every counter key is created up front: a key added lazily would change
        # the dict size while a concurrent /cyrrus/status request is iterating it.
        self.counters = {"requests": 0, "injected": 0, "skipped": 0, "fail_open": 0,
                         "record_refused": 0}
        self.projector = projector or self._make_projector()
        # One persistent event loop, owned by this gateway and driven on a
        # dedicated thread.  Every coroutine the gateway runs (context build,
        # history summariser, record_turn) is scheduled onto THIS loop so the
        # Projector's asyncio.Lock primitives never cross event loops.  The old
        # design ran a fresh asyncio.run() per request thread, which shared
        # those loop-bound locks across loops and failed open under concurrency.
        self._loop = None
        self._loop_thread = None
        self._bg_futures = set()          # fire-and-forget futures awaiting record_turn
        self._turn_windows = 0            # handlers that owe a record_turn (see _reserve_turn)
        # One condition guards all shutdown state: _bg_futures, _turn_windows,
        # _closed and _stopping.  Every decision about "can this turn still be
        # scheduled?" and "may the loop stop?" is taken under it, which is what
        # makes the two unable to interleave and lose work.
        self._bg_cv = threading.Condition()
        self._closed = False              # close() has begun: no more fire-and-forget
        self._stopping = False            # the loop is about to stop: no work accepted
        self._start_event_loop()
        self.warmup_thread = None
        self._start_warmup()

    def _start_event_loop(self):
        """Create the persistent loop and run it on a daemon thread.

        Daemon so the process can never be blocked at interpreter exit by the
        loop thread; ``close()`` stops and joins it promptly when called.
        """
        self._loop = asyncio.new_event_loop()

        def _drive():
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_forever()
            finally:
                # run_forever returned because close() asked it to stop.  Cancel
                # anything still pending, drain the default executor (used by
                # asyncio.to_thread in the SQLite backend), then close.
                try:
                    pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception:  # noqa: BLE001 - shutdown is best-effort
                    pass
                try:
                    if hasattr(self._loop, "shutdown_default_executor"):
                        self._loop.run_until_complete(self._loop.shutdown_default_executor())
                except Exception:  # noqa: BLE001
                    pass
                self._loop.close()

        self._loop_thread = threading.Thread(target=_drive, name="cyrrus-event-loop", daemon=True)
        self._loop_thread.start()

    def _context_timeout(self):
        try:
            return float(self.options.get("context_timeout", 60.0))
        except (TypeError, ValueError):
            return 60.0

    def _shutdown_timeout(self):
        """Drain budget for close(), in seconds (``gateway.shutdown_timeout``).

        Measured on this machine by the 200-concurrent-request, close-mid-load
        test in tests/test_gateway.py, with the burst fully drained (30 runs per
        interpreter, min/median/max of the time close() took):

            python 3.13:  2.079 / 3.881 / 8.089 s
            python 3.9:   9.266 / 10.906 / 13.266 s

        The 5 s budget close() used to carry was exhausted by every single 3.9
        run; 30 s leaves ~2.3x headroom over the slowest measured drain and
        ~3.7x over the slowest 3.13 drain, so a backlog a few times the tested
        burst is still drained rather than traded for a prompt exit. It costs
        nothing in the normal case because close() returns as soon as the queue
        is empty; it only bites when a task is wedged, which is exactly the case
        where a short budget would lose turns a client was already served for.
        Callers needing a hard bound pass ``timeout=`` explicitly.
        """
        try:
            value = float(self.options.get("shutdown_timeout", 30.0))
        except (TypeError, ValueError):
            return 30.0
        return value if value >= 0.0 else 30.0

    def _submit(self, coro, timeout=None):
        """Run ``coro`` on the persistent loop from a request thread and block.

        Raises the coroutine's exception (real model/memory errors) so callers
        keep their fail-open behaviour, or ``concurrent.futures.TimeoutError``
        if it exceeds the timeout.  Because the coroutine always runs on the
        gateway's single loop, it can never raise a cross-loop error.
        """
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("gateway event loop is not running")
        if timeout is None:
            timeout = self._context_timeout()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise

    def _reserve_turn(self):
        """Claim the right to record this request's turn; False if shutting down.

        A handler calls this BEFORE it writes any response byte.  From that
        moment until ``_release_turn`` the gateway is not allowed to stop its
        event loop, so a client that can see a 200 is guaranteed that its
        record_turn — and the facts it extracts — will still run.  Returning
        False means shutdown already decided to stop, and the caller must refuse
        the request loudly instead of answering 200 and losing the turn.
        """
        with self._bg_cv:
            if self._stopping:
                return False
            self._turn_windows += 1
            return True

    def _release_turn(self):
        with self._bg_cv:
            self._turn_windows -= 1
            self._bg_cv.notify_all()

    def _fire(self, coro):
        """Schedule ``coro`` on the persistent loop without blocking the caller.

        Used for the post-response record_turn; failures are logged, not raised.

        Shutdown rules: once ``close()`` has begun (``_closed``), the same work
        is still scheduled but the calling thread waits for it, so no turn that
        a client was already promised can be left running past the drain.  Once
        the loop is being stopped (``_stopping``) the work cannot run at all, and
        that is refused with a warning and a counter — never dropped silently.
        """
        with self._bg_cv:
            loop = self._loop
            closing = self._closed
            accepted = not self._stopping and loop is not None and loop.is_running()
            future = None
            if accepted:
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                self._bg_futures.add(future)
                if closing:
                    self._bg_cv.notify_all()
        if future is None:
            close_coro = getattr(coro, "close", None)
            if close_coro is not None:
                close_coro()  # don't leak an un-awaited coroutine
            with self._bg_cv:
                self.counters["record_refused"] = self.counters.get("record_refused", 0) + 1
            log.warning(
                "Cyrrus background work refused: the gateway event loop is shutting down; "
                "this turn will not be recorded."
            )
            return None

        def _done(fut):
            with self._bg_cv:
                self._bg_futures.discard(fut)
                self._bg_cv.notify_all()
            try:
                exc = fut.exception()
            except concurrent.futures.CancelledError:
                return
            if exc is not None:
                log.warning("Cyrrus background task failed: %s", exc)

        future.add_done_callback(_done)
        if closing:
            # Closing: run it inline (block here) rather than let close() finish
            # with this turn still queued.  The wait is bounded so a wedged task
            # cannot wedge this request thread too; the future stays in
            # _bg_futures, so the drain keeps accounting for it either way.
            try:
                future.result(timeout=self._context_timeout())
            except concurrent.futures.TimeoutError:
                log.warning("Cyrrus shutdown record still running after %ss; "
                            "the drain will keep waiting for it.", self._context_timeout())
            except Exception as exc:  # noqa: BLE001 - reported, never raised to a served client
                log.warning("Cyrrus background task failed during shutdown: %s", exc)
        return future

    def close(self, timeout=None):
        """Drain in-flight background work, then stop and join the loop thread.

        Idempotent.  Safe to call even if the loop never started.  ``timeout``
        is the drain budget in seconds and defaults to
        ``_shutdown_timeout()`` (``gateway.shutdown_timeout``).

        Order matters and is the whole fix: the closing flag is set first, the
        drain then repeats until *nothing* is pending — neither a queued
        record_turn nor a handler that still owes one — and only after that is
        the loop asked to stop, atomically with the flag that makes further work
        refuse instead of schedule.  A single snapshot of the futures was what
        used to lose turns whose handlers were mid-response.

        Giving up is never silent: the drain timeout logs the three counts that
        make up the loss (queued, still in flight, already refused) and states
        how many served turns will not be recorded.
        """
        with self._bg_cv:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
        if loop is None:
            return
        try:
            budget = self._shutdown_timeout() if timeout is None else max(float(timeout), 0.0)
        except (TypeError, ValueError):
            budget = self._shutdown_timeout()
        deadline = time.monotonic() + budget
        with self._bg_cv:
            while True:
                if not self._bg_futures and self._turn_windows == 0:
                    # Atomic with _reserve_turn()/_fire(): after this point no
                    # thread can schedule anything, so stopping the loop cannot
                    # cancel work a client was promised.
                    self._stopping = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    queued = len(self._bg_futures)
                    refused = self.counters.get("record_refused", 0)
                    log.warning(
                        "Cyrrus shutdown drain timed out after %ss: %d record_turn "
                        "task(s) still queued, %d request(s) still in flight, %d turn(s) "
                        "already refused since closing began. At least %d turn(s) that "
                        "were served a response will not be recorded.",
                        budget, queued, self._turn_windows, refused, queued + refused,
                    )
                    self._stopping = True
                    break
                self._bg_cv.wait(remaining)
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass  # loop already stopped/closed
        if self._loop_thread is not None and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=budget)
            if self._loop_thread.is_alive():
                log.warning("Cyrrus event loop thread did not exit within %ss.", budget)
        self._loop = None
        self._loop_thread = None


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
            context, trace = self._submit(self.projector.build_context(user_text, session))
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
            summarizer_timeout = getattr(self.projector, "summarizer_timeout", 10.0)
            # Schedule on the shared loop; give headroom past the summariser's
            # own internal timeout so that one fires first and reports cleanly.
            summary = self._submit(
                _run_history_summarizer(summarizer, dropped, summarizer_timeout),
                timeout=summarizer_timeout + 5.0,
            )
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
            records_turn = not payload.get("tools") and not any(
                m.get("role") == "tool" for m in payload.get("messages", []))
            # Claim the turn before a single response byte leaves: the client is
            # about to see a 200, and after this point shutdown must wait for our
            # record_turn instead of stopping the loop underneath it.  Refusing
            # here is the clear "not recorded" answer; answering 200 and dropping
            # the turn is what the old fire-and-forget did.
            if records_turn and not gateway._reserve_turn():
                return self._json(503, {"error": {"message": "gateway is shutting down; this turn was not recorded", "type": "shutdown"}})
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
                if records_turn:
                    gateway._fire(gateway.projector.record_turn(session, user_text, assistant))
                gateway.add_trace(session, trace, started)
            except (URLError, ValueError) as exc:
                self._json(502, {"error": {"message": str(exc), "type": "upstream_error"}})
            finally:
                if records_turn:
                    gateway._release_turn()
    return Handler


def create_server(config, projector=None, host=None, port=None, log_prompts=False):
    options = config["gateway"]
    host = host or options["host"]; port = options["port"] if port is None else port
    if not _is_loopback(host) and not options.get("api_key_env"):
        raise ValueError("Non-loopback gateway binding requires gateway.api_key_env")
    gateway = Gateway(config, projector=projector, log_prompts=log_prompts)
    while True:
        try:
            server = _GatewayServer((host, port), make_handler(gateway)); server.gateway = gateway; return server
        except OSError:
            if port == 0:
                gateway.close()
                raise
            port += 1


def serve(config, host=None, port=None, log_prompts=False):
    server = create_server(config, host=host, port=port, log_prompts=log_prompts)
    print("Cyrrus gateway: http://%s:%s/v1  model=%s  mode=%s" % (server.server_address[0], server.server_address[1], config.get("provider", {}).get("model") or "(unset)", config["gateway"]["mode"]))
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        server.gateway.close()
