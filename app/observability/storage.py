"""Traces e feedback no LangSmith, sem banco local nem conteúdo das conversas."""

import copy
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from itertools import islice
from uuid import NAMESPACE_URL, uuid4, uuid5

from langsmith import Client
from langsmith.utils import LangSmithConflictError, LangSmithNotFoundError

logger = logging.getLogger(__name__)
TAG = "quimia-sre-v1"
FEEDBACK_KEY = "quimia.resolved"
_cache = {}
_cache_lock = threading.Lock()


class StorageUnavailable(RuntimeError):
    """Configuração ausente ou serviço de observabilidade indisponível."""


def enabled():
    return os.getenv("LANGSMITH_TRACING", "false").lower() == "true"


def project():
    return os.getenv("LANGSMITH_PROJECT", "quimia-agent")


@lru_cache(maxsize=1)
def get_client():
    if not enabled() or not os.getenv("LANGSMITH_API_KEY"):
        raise StorageUnavailable("Configure LANGSMITH_TRACING=true e LANGSMITH_API_KEY no servidor.")
    return Client(
        api_key=os.environ["LANGSMITH_API_KEY"],
        workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID") or None,
        timeout_ms=5000,
        auto_batch_tracing=True,
        tracing_sampling_rate=1.0,
        omit_traced_runtime_info=True,
        hide_inputs=True,
        hide_outputs=True,
        hide_metadata=False,
    )


def _timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


def _order(start, run_id):
    return start.strftime("%Y%m%dT%H%M%S%fZ") + str(run_id)


def save(record):
    if not enabled():
        return
    client = get_client()
    root_id = record["id"]
    start = _timestamp(record["created"])
    root_order = _order(start, root_id)
    failed = record["http_status"] >= 500 or record.get("degraded", False)
    client.create_run(
        id=root_id, trace_id=root_id, dotted_order=root_order,
        project_name=project(), name="quimia." + record.get("operation", "chat"),
        run_type="chain", inputs={}, outputs={}, start_time=start,
        end_time=start + timedelta(milliseconds=record["duration_ms"]),
        error="Falha técnica" if failed else None, tags=[TAG],
        extra={"metadata": {"quimia_sre": record, "http_status": record["http_status"],
                            "outcome": record["outcome"], "route": record["route"]}},
    )
    # Primeiro os spans mais abrangentes, para permitir pais com etapas concorrentes.
    parents = []
    spans = sorted(record["spans"], key=lambda s: (s["start_ms"], -s["duration_ms"]))
    for item in spans:
        end_ms = item["start_ms"] + item["duration_ms"]
        candidates = [p for p in parents if p["start"] <= item["start_ms"]
                      and p["end"] >= end_ms and
                      (p["start"] < item["start_ms"] or p["end"] > end_ms)]
        parent = min(candidates, key=lambda p: p["end"] - p["start"], default=None)
        run_id = str(uuid4())
        span_start = start + timedelta(milliseconds=item["start_ms"])
        order = (parent["order"] if parent else root_order) + "." + _order(span_start, run_id)
        client.create_run(
            id=run_id, trace_id=root_id, parent_run_id=parent["id"] if parent else root_id,
            dotted_order=order, project_name=project(), name=item["name"],
            run_type="tool" if item["kind"] == "tool" else "chain",
            inputs={}, outputs={}, start_time=span_start,
            end_time=start + timedelta(milliseconds=end_ms), error=item.get("error"),
            extra={"metadata": {"kind": item["kind"]}},
        )
        parents.append({"id": run_id, "order": order, "start": item["start_ms"],
                        "end": end_ms, "name": item["name"]})
    for call in record["calls"]:
        candidates = [p for p in parents if p["name"] == call.get("stage")]
        parent = next((p for p in candidates if p["start"] <= call.get("start_ms", p["start"])
                       <= p["end"]), None)
        offset = call.get("start_ms", parent["start"] if parent else 0)
        duration = call.get("duration_ms", parent["end"] - parent["start"] if parent else 0)
        call_start = start + timedelta(milliseconds=offset)
        run_id = str(uuid4())
        usage = {}
        if call.get("input_tokens") is not None and call.get("output_tokens") is not None:
            usage = {"input_tokens": call["input_tokens"], "output_tokens": call["output_tokens"],
                     "total_tokens": call["input_tokens"] + call["output_tokens"]}
        if call.get("estimated_cost_usd") is not None:
            usage["total_cost"] = call["estimated_cost_usd"]
        metadata = {"ls_provider": "google_genai" if call["kind"] == "embedding" else "commandcode",
                    "ls_model_name": call["model"], "fallback": call.get("fallback", False),
                    "estimated_cost_usd": call.get("estimated_cost_usd"),
                    "pricing_as_of": call.get("pricing_as_of"), "usage_unknown": not bool(usage)}
        if usage:
            # Formato do SDK RunTree.end: preserva usage mesmo com inputs/outputs ocultos.
            metadata["usage_metadata"] = usage
        client.create_run(
            id=run_id, trace_id=root_id, parent_run_id=parent["id"] if parent else root_id,
            dotted_order=(parent["order"] if parent else root_order) + "." + _order(call_start, run_id),
            project_name=project(), name=call["model"],
            run_type="embedding" if call["kind"] == "embedding" else "llm",
            inputs={}, outputs={}, start_time=call_start,
            end_time=call_start + timedelta(milliseconds=duration), error=call.get("error"),
            extra={"metadata": metadata},
        )


def _read_record(run):
    data = (run.extra or {}).get("metadata", {}).get("quimia_sre")
    if not isinstance(data, dict) or data.get("id") != str(run.id):
        raise KeyError(str(run.id))
    return data


def records(days=7, limit=20000):
    client = get_client()
    key = (id(client), project(), days, limit)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return copy.deepcopy(cached[1])
        try:
            # O SDK envia `limit` também ao servidor, cujo máximo por página é
            # 100. Sem esse argumento ele pagina por cursor; islice limita o
            # total local sem transformar 20.001 no tamanho de uma página.
            runs = list(islice(client.list_runs(
                project_name=project(), is_root=True, filter=f'has(tags, "{TAG}")',
                start_time=datetime.now(timezone.utc) - timedelta(days=days),
                select=["id", "extra", "start_time"],
            ), limit + 1))
            rows = [_read_record(run) for run in runs[:limit]]
            rows.sort(key=lambda row: row["created"], reverse=True)
            by_id = {row["id"]: row for row in rows}
            for row in rows:
                row["resolved"] = None
            ids = list(by_id)
            # Consulta em lotes: evita uma requisição por turno.
            for offset in range(0, len(ids), 100):
                feedbacks = client.list_feedback(run_ids=ids[offset:offset + 100],
                                                 feedback_key=[FEEDBACK_KEY])
                latest = {}
                for feedback in feedbacks:
                    run_id = str(feedback.run_id)
                    previous = latest.get(run_id)
                    if previous is None or feedback.modified_at > previous.modified_at:
                        latest[run_id] = feedback
                for run_id, feedback in latest.items():
                    if run_id in by_id and feedback.score in (0, 1):
                        by_id[run_id]["resolved"] = bool(feedback.score)
            result = (rows, len(runs) > limit)
            _cache[key] = (time.monotonic(), copy.deepcopy(result))
            return result
        except LangSmithNotFoundError:
            # Um projeto novo ainda não existe até a ingestão do primeiro trace.
            return [], False
        except Exception as exc:
            logger.warning("Falha ao consultar LangSmith: %s", type(exc).__name__)
            raise StorageUnavailable("Não foi possível consultar as métricas no LangSmith agora.") from None


def feedback(trace_id, resolved):
    client = get_client()
    try:
        try:
            run = client.read_run(trace_id)
        except LangSmithNotFoundError:
            raise KeyError(trace_id) from None
        # Não permite confirmar traces de outros projetos ou aplicações.
        selected_project = client.read_project(project_name=project())
        if run.session_id != selected_project.id or TAG not in (run.tags or []):
            raise KeyError(trace_id)
        record = _read_record(run)
        if record["http_status"] != 200 or record["outcome"] != "respondido" or record.get("degraded"):
            raise ValueError("Somente respostas de especialistas aprovadas podem receber confirmação de resolução.")
        feedback_id = uuid5(NAMESPACE_URL, f"quimia:{trace_id}:{FEEDBACK_KEY}")
        try:
            client.read_feedback(feedback_id)
        except LangSmithNotFoundError:
            try:
                client.create_feedback(run_id=trace_id, key=FEEDBACK_KEY, score=int(resolved),
                                       feedback_id=feedback_id)
            except LangSmithConflictError:
                client.update_feedback(feedback_id, score=int(resolved))
        else:
            client.update_feedback(feedback_id, score=int(resolved))
        with _cache_lock:
            _cache.clear()
    except (KeyError, ValueError):
        raise
    except Exception as exc:
        logger.warning("Falha no feedback LangSmith: %s", type(exc).__name__)
        raise StorageUnavailable("Não foi possível registrar o feedback no LangSmith agora.") from None


def flush():
    if get_client.cache_info().currsize:
        get_client().flush()
