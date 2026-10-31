"""Contexto por requisição e spans concorrentes; nunca guarda conteúdo de mensagens."""

import functools
import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from langsmith import tracing_context

from app.observability import storage

logger = logging.getLogger(__name__)
current = ContextVar("sre_trace", default=None)
active_stage = ContextVar("sre_stage", default=None)
_active = 0
_active_lock = threading.Lock()


class Trace:
    def __init__(self, operation="chat"):
        self.id = str(uuid4())
        self.operation = operation
        self.created = time.time()
        self.started = time.perf_counter()
        self.spans = []
        self.calls = []
        self.outcome = "desconhecido"
        self.route = "desconhecida"
        self.degraded = False
        self.lock = threading.Lock()

    def elapsed(self):
        return (time.perf_counter() - self.started) * 1000

    def add(self, bucket, item):
        with self.lock:
            getattr(self, bucket).append(item)

    def finish(self, status):
        if self.outcome == "desconhecido" and status >= 400:
            self.outcome = "validacao" if status == 422 else "erro"
        record = {"id": self.id, "created": self.created, "duration_ms": self.elapsed(),
                  "operation": self.operation,
                  "http_status": status, "outcome": self.outcome, "route": self.route,
                  "degraded": self.degraded, "spans": self.spans, "calls": self.calls}
        try:
            from app.observability.metrics import call_cost, pricing
            prices = pricing()
            for call in record["calls"]:
                call["estimated_cost_usd"] = call_cost(call, prices["models"])
                call["pricing_as_of"] = prices["as_of"]
            storage.save(record)
        except Exception:
            logger.exception("Falha ao persistir telemetria; trace_id=%s", self.id)
        logger.info("chat_trace id=%s status=%s outcome=%s duration_ms=%.2f",
                    self.id, status, self.outcome, record["duration_ms"])


def mark(outcome=None, route=None, degraded=False):
    trace = current.get()
    if trace:
        if outcome:
            trace.outcome = outcome
        if route:
            trace.route = route
        trace.degraded = trace.degraded or degraded


@contextmanager
def span(name, kind="dependency"):
    trace = current.get()
    if trace is None:
        yield
        return
    start = trace.elapsed()
    error = None
    token = active_stage.set(name) if kind in ("stage", "agent") else None
    try:
        yield
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        trace.add("spans", {"name": name, "kind": kind, "start_ms": start,
                            "duration_ms": trace.elapsed() - start, "error": error})
        if token is not None:
            active_stage.reset(token)


def stage(name, kind="stage"):
    def decorate(fn):
        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            label = name(*args, **kwargs) if callable(name) else name
            with span(label, kind):
                return await fn(*args, **kwargs)
        return wrapped
    return decorate


def record_usage(model, usage, kind="decision", error=None, started_at=None):
    trace = current.get()
    if not trace:
        return
    usage = usage or {}
    timing = {}
    if started_at is not None:
        timing = {"start_ms": (started_at - trace.started) * 1000,
                  "duration_ms": (time.perf_counter() - started_at) * 1000}
    trace.add("calls", {"model": model, "kind": kind, "stage": active_stage.get(),
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "error": error, "fallback": False, **timing})


def in_progress():
    with _active_lock:
        return _active


async def observe_request(request, call_next):
    global _active
    if request.method != "POST" or request.url.path not in {"/chat", "/chat/sessions/close"}:
        return await call_next(request)
    trace = Trace("chat" if request.url.path == "/chat" else "session_summary")
    if trace.operation == "session_summary":
        trace.route = "resumo_sessao"
        trace.outcome = "resumo"
    token = current.set(trace)
    with _active_lock:
        _active += 1
    status = 500
    try:
        # A exportação usa apenas os metadados dos callbacks. Impede que o tracing
        # automático capture prompts, respostas, evidências e estado do grafo.
        with tracing_context(enabled=False):
            response = await call_next(request)
        status = response.status_code
        response.headers["X-Trace-Id"] = trace.id
        return response
    finally:
        await asyncio.to_thread(trace.finish, status)
        current.reset(token)
        with _active_lock:
            _active -= 1
