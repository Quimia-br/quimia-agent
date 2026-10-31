"""Callbacks nativos do LangChain: usage_metadata e falhas, sem prompts/outputs."""

import os
import threading

from langchain_core.callbacks import BaseCallbackHandler

from app.observability.telemetry import active_stage


class MetricsCallback(BaseCallbackHandler):
    run_inline = True

    def __init__(self, trace):
        self.trace = trace
        self.pending = {}
        self.lock = threading.Lock()

    def _start(self, run_id, model, kind):
        with self.lock:
            self.pending[str(run_id)] = {"model": model, "kind": kind,
                "stage": active_stage.get(), "start_ms": self.trace.elapsed()}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get("invocation_params") or {}
        self._start(run_id, params.get("model") or params.get("model_name") or "unknown", "llm")

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._start(run_id, (serialized or {}).get("name", "tool"), "tool")

    def _finish(self, run_id, usage=None, error=None):
        with self.lock:
            call = self.pending.pop(str(run_id), None)
        if call is None:
            return
        call.update(duration_ms=self.trace.elapsed() - call["start_ms"], error=error)
        if call["kind"] == "tool":
            self.trace.add("spans", {"name": call["model"], "kind": "tool",
                                    "start_ms": call["start_ms"], "duration_ms": call["duration_ms"], "error": error})
            return
        usage = usage or {}
        call.update(input_tokens=usage.get("input_tokens", usage.get("prompt_tokens")),
                    output_tokens=usage.get("output_tokens", usage.get("completion_tokens")),
                    fallback=call["model"] == os.getenv("COMMANDCODE_MODEL_FALLBACK", "xiaomi/mimo-v2.6-pro"))
        self.trace.add("calls", call)

    def on_llm_end(self, response, *, run_id, **kwargs):
        usage = None
        if response.generations and response.generations[0]:
            msg = getattr(response.generations[0][0], "message", None)
            usage = getattr(msg, "usage_metadata", None)
        if not usage:
            usage = (response.llm_output or {}).get("token_usage")
        self._finish(run_id, usage)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, error=type(error).__name__)

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._finish(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._finish(run_id, error=type(error).__name__)
