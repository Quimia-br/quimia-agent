import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability import storage
from app.observability.callbacks import MetricsCallback
from app.observability.metrics import snapshot, percentile
from app.observability.telemetry import Trace, current, span, stage
import app.main as main
import app.routes.chat_routes as chat
from app.agent.workflow import ChatRunResult


def record(**changes):
    import time
    return {"id": str(uuid4()), "created": time.time(), "duration_ms": 100,
            "http_status": 200, "outcome": "respondido", "route": "faq", "degraded": False,
            "calls": [], "spans": [], "resolved": None, **changes}


def usage(model="xiaomi/mimo-v2.6-flash", **changes):
    return {"model": model, "input_tokens": 1000000, "output_tokens": 1000000,
            "kind": "llm", "error": None, "fallback": False, **changes}


def test_cost_roi_and_forecasts_use_confirmed_resolutions_only():
    r = record(calls=[usage()], resolved=True)
    m = snapshot([r], minutes_saved=6, hourly_cost=20, fixed_weekly_cost=0, turns_per_user=5)
    s = m["summary"]
    assert s["known_cost_usd"] == pytest.approx(.42)
    assert s["cost_per_resolution_usd"] == pytest.approx(.42)
    assert s["benefit_usd"] == pytest.approx(2)
    assert s["roi"] == pytest.approx((2-.42)/.42)
    assert m["scenarios"][0]["estimated_cost_usd"] == pytest.approx(210)
    assert m["scenarios"][1]["estimated_cost_usd"] == pytest.approx(2100)
    assert snapshot([record()], minutes_saved=6, hourly_cost=20)["summary"]["roi"] is None


def test_unknown_cost_is_reported_as_partial_not_free():
    m = snapshot([record(calls=[usage(), usage("unpriced"), usage(input_tokens=None)])])
    assert m["summary"]["known_cost_usd"] == pytest.approx(.42)
    assert m["summary"]["cost_partial"] is True
    assert m["summary"]["unpriced_or_unknown_calls"] == 2
    assert m["summary"]["cost_coverage"] == pytest.approx(1/3)


def test_summary_cost_is_amortized_without_changing_chat_slo_denominator():
    chat_record = record(calls=[usage()])
    summary_record = record(operation="session_summary", outcome="resumo", calls=[usage()], http_status=503)
    report = snapshot([chat_record, summary_record])
    assert report["summary"]["requests"] == 1
    assert report["summary"]["session_summary_requests"] == 1
    assert report["summary"]["session_summary_errors"] == 1
    assert report["summary"]["error_rate"] == 0
    assert report["summary"]["known_cost_usd"] == pytest.approx(.84)
    assert report["scenarios"][0]["estimated_cost_usd"] == pytest.approx(420)


def test_stored_cost_does_not_change_with_price_table(monkeypatch):
    trace=Trace()
    trace.calls=[usage()]
    trace.finish(200)
    monkeypatch.setenv("SRE_PRICING_JSON", json.dumps({"xiaomi/mimo-v2.6-flash":{"input":10,"output":20}}))
    rows,_=storage.records()
    assert snapshot(rows)["summary"]["known_cost_usd"] == pytest.approx(.42)


def test_slo_distinguishes_blocked_input_from_error_and_degraded_200():
    m = snapshot([record(outcome="bloqueado_entrada"),record(http_status=503),record(degraded=True)])
    assert m["summary"]["error_rate"] == pytest.approx(2/3)
    assert m["summary"]["blocked_input"] == 1
    assert m["slo"]["ok"] is False
    assert percentile([1, 2, 3, 4], .95) == 4
    assert snapshot([])["slo"]["ok"] is None
    assert snapshot([])["summary"]["latency_p95_ms"] is None


def test_callbacks_capture_fallback_and_tokens_without_messages(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_MODEL_FALLBACK", "backup")
    trace = Trace(); handler = MetricsCallback(trace)
    first, second = uuid4(), uuid4()
    handler.on_chat_model_start({}, [["secret message"]], run_id=first, invocation_params={"model":"primary"})
    handler.on_llm_error(RuntimeError("secret error body"), run_id=first)
    handler.on_chat_model_start({}, [["secret message"]], run_id=second, invocation_params={"model":"backup"})
    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="secret answer",usage_metadata={"input_tokens":10,"output_tokens":5,"total_tokens":15}))]])
    handler.on_llm_end(response, run_id=second)
    assert trace.calls[0]["error"] == "RuntimeError"
    assert trace.calls[1]["fallback"] is True
    assert trace.calls[1]["input_tokens"] == 10
    assert "secret" not in json.dumps(trace.calls)


def test_trace_contexts_are_isolated_with_concurrent_requests():
    @stage("faq")
    async def work():
        await asyncio.sleep(.001)
    async def run():
        trace = Trace(); token = current.set(trace)
        try:
            await work()
            return trace
        finally:
            current.reset(token)
    async def both():
        return await asyncio.gather(run(), run())
    a,b = asyncio.run(both())
    assert a.id != b.id
    assert len(a.spans) == len(b.spans) == 1


def test_feedback_is_idempotent_and_persistent_and_rejects_greetings():
    r = record(); storage.save(r)
    storage.feedback(r["id"], True)
    storage.feedback(r["id"], True)
    assert storage.records()[0][0]["resolved"] is True
    storage.feedback(r["id"], False)
    assert storage.records()[0][0]["resolved"] is False
    greeting = record(outcome="saudacao"); storage.save(greeting)
    with pytest.raises(ValueError): storage.feedback(greeting["id"], True)


def test_monitor_access_and_chat_failure_are_observed_without_content(monkeypatch):
    monkeypatch.setattr(main,"validar_config",lambda:[])
    monkeypatch.setattr(main,"close_mongo",lambda:None)
    monkeypatch.setattr(chat,"load_chat_context",lambda *args:"")
    async def fail(*args): raise RuntimeError("private database error")
    monkeypatch.setattr(chat,"run_chat",fail)
    with TestClient(main.create_app(), client=("127.0.0.1", 50000)) as client:
        page = client.get("/monitor.html")
        assert page.status_code == 200
        assert '/monitor-assets/icon/logo-quimia-symbol.svg' in page.text
        for asset, mime in (("monitor.css", "text/css"), ("brand.css", "text/css"),
                            ("monitor.js", "text/javascript"),
                            ("icon/logo-quimia-symbol.svg", "image/svg+xml"),
                            ("icon/logo-quimia.svg", "image/svg+xml")):
            response = client.get("/monitor-assets/" + asset)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(mime)
        assert client.get("/monitor-assets/icon/index.html").status_code == 404
        assert client.get("/monitor-assets/unknown").status_code == 404
        r=client.post("/chat",json={"session_id":"private-session","user_id":str(uuid4()),"pergunta":"private question"})
        assert r.status_code==503
        assert r.headers.get("x-trace-id")
        metrics=client.get("/monitor")
        assert metrics.status_code==200
        assert metrics.json()["summary"]["errors"]==1
        assert "private" not in metrics.text
        assert client.get("/monitor?days=0").status_code==422
    with TestClient(main.create_app(), client=("192.0.2.1", 50000)) as remote:
        assert remote.get("/monitor").status_code == 403
        assert remote.post(f"/monitor/feedback/{uuid4()}", json={"resolved": True}).status_code == 403


def test_real_langchain_callbacks_follow_the_graph_and_count_calls(monkeypatch):
    import httpx
    from langchain_openai import ChatOpenAI
    from langchain_core.tracers.langchain import LangChainTracer
    import app.agent.llms as llms

    # Mesmo ativado no ambiente, o tracing automático não pode enviar o estado
    # do grafo. Somente o exportador de metadados deve receber os eventos.
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    native_tracers = []
    def reject_native_tracer(*args, **kwargs):
        native_tracers.append(True)
        raise AssertionError("Tracing automático de conteúdo não autorizado")
    monkeypatch.setattr(LangChainTracer, "__init__", reject_native_tracer)

    monkeypatch.setattr(main,"validar_config",lambda:[])
    monkeypatch.setattr(main,"close_mongo",lambda:None)
    monkeypatch.setattr(chat,"load_chat_context",lambda *args:"")
    monkeypatch.setattr(chat,"save_turn",lambda *args:None)
    monkeypatch.setenv("COMMANDCODE_API_KEY","test")
    monkeypatch.setenv("COMMANDCODE_MODEL","xiaomi/mimo-v2.6-flash")

    def handle(request):
        body=json.loads(request.content)
        prompt=body["messages"][0]["content"]
        if '"title": "InputDecision"' in prompt:
            output={"categoria":"permitido","motivo":"Saudação"}
        elif '"title": "OrchestratorResult"' in prompt:
            output={"status":"saudacao","pergunta_original":"oi","rotas":[],"resposta":"Olá!"}
        elif '"title": "OutputDecision"' in prompt:
            output={"segura":True,"motivo":"Saudação segura"}
        else:
            raise AssertionError("Modelo inesperado")
        return httpx.Response(200,json={"id":"test","object":"chat.completion","created":0,
            "model":body["model"],"choices":[{"index":0,"finish_reason":"stop",
            "message":{"role":"assistant","content":json.dumps(output)}}],
            "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}})

    sync=httpx.Client(transport=httpx.MockTransport(handle))
    asynchronous=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(llms,"ChatOpenAI",lambda **kwargs:ChatOpenAI(**kwargs,http_client=sync,http_async_client=asynchronous))
    try:
        with TestClient(main.create_app(), client=("127.0.0.1", 50000)) as client:
            result=client.post("/chat",json={"session_id":"s","user_id":str(uuid4()),"pergunta":"oi"})
            assert result.status_code==200
            report=client.get("/monitor").json()
            assert report["summary"]["input_tokens"]==30
            assert report["summary"]["output_tokens"]==15
            assert report["by_model"][0]["calls"]==3
            assert {s["name"] for s in report["by_stage"]} >= {"orquestrador","guardrail_entrada","guardrail_saida","sintetizador"}
            assert "mensagens" not in json.dumps(storage.records()[0])
            assert not native_tracers
    finally:
        sync.close()
        asyncio.run(asynchronous.aclose())


def test_langsmith_exports_hierarchy_tokens_and_cost_without_content(isolated_sre_storage):
    fake = isolated_sre_storage
    trace = Trace()
    trace.outcome = 'respondido'
    trace.route = 'faq'
    trace.spans = [
        {'name': 'especialistas', 'kind': 'stage', 'start_ms': 0, 'duration_ms': 40, 'error': None},
        {'name': 'faq', 'kind': 'agent', 'start_ms': 5, 'duration_ms': 30, 'error': None},
        {'name': 'juiz', 'kind': 'stage', 'start_ms': 40, 'duration_ms': 10, 'error': None},
    ]
    trace.calls = [usage(stage='faq', start_ms=10, duration_ms=20),
                   usage('typesafe/jev-1.14.0', kind='decision', stage='juiz', start_ms=41, duration_ms=8)]
    trace.started -= .06
    trace.finish(200)
    runs = list(fake.runs.values())
    root = fake.runs[trace.id]
    faq = next(r for r in runs if r.name == 'faq')
    specialists = next(r for r in runs if r.name == 'especialistas')
    llm = next(r for r in runs if r.run_type == 'llm' and r.name.startswith('xiaomi'))
    assert str(root.id) == trace.id
    assert faq.parent_run_id == str(specialists.id)
    assert llm.parent_run_id == str(faq.id)
    assert llm.dotted_order.startswith(faq.dotted_order + '.')
    assert llm.extra['metadata']['usage_metadata']['total_tokens'] == 2000000
    assert llm.extra['metadata']['usage_metadata']['total_cost'] == pytest.approx(.42)
    assert all(r.inputs == {} and r.outputs == {} for r in runs)
    assert all(r.trace_id == trace.id for r in runs)


def test_langsmith_reads_are_cached_bounded_and_feedback_is_single(isolated_sre_storage):
    fake = isolated_sre_storage
    rows = [record(), record()]
    for row in rows:
        storage.save(row)
    loaded, truncated = storage.records(limit=1)
    assert len(loaded) == 1 and truncated
    storage.records(limit=1)
    assert fake.queries == 1
    storage.feedback(rows[0]['id'], True)
    storage.feedback(rows[0]['id'], False)
    assert len(fake.feedbacks) == 1
    assert storage.records()[0][1]['resolved'] is False
    with pytest.raises(KeyError):
        storage.feedback(str(uuid4()), True)
    fake.runs[rows[0]['id']].session_id = uuid4()
    with pytest.raises(KeyError):
        storage.feedback(rows[0]['id'], True)


def test_langsmith_outage_is_explicit_and_does_not_break_chat(monkeypatch, isolated_sre_storage):
    monkeypatch.setattr(main, 'validar_config', lambda: [])
    monkeypatch.setattr(main, 'close_mongo', lambda: None)
    def unavailable():
        raise storage.StorageUnavailable('LangSmith indisponível')
    monkeypatch.setattr(storage, 'get_client', unavailable)
    with TestClient(main.create_app(), client=('127.0.0.1', 50000)) as client:
        assert client.get('/monitor').status_code == 503
        assert client.post(f'/monitor/feedback/{uuid4()}', json={'resolved': True}).status_code == 503
        # Erro de validação continua sendo 422 mesmo com falha ao exportar o trace.
        assert client.post('/chat', json={}).status_code == 422
    monkeypatch.setattr(storage, 'enabled', lambda: False)
    storage.save(record())  # Desativado não tenta acessar o cliente nem cria arquivo.


def test_real_langsmith_sdk_serializes_usage_in_metadata(monkeypatch):
    from langsmith import Client
    client = Client(api_url='https://langsmith.example.invalid', api_key='test',
                    auto_batch_tracing=False, hide_inputs=True, hide_outputs=True,
                    omit_traced_runtime_info=True, hide_metadata=False)
    sent = []
    def capture(self, method, path, *, request_kwargs, **kwargs):
        assert method == 'POST' and path.endswith('/runs')
        sent.append(json.loads(request_kwargs['data']))
    monkeypatch.setattr(Client, 'request_with_retries', capture)
    monkeypatch.setattr(storage, 'get_client', lambda: client)
    trace = Trace()
    trace.calls = [usage()]
    trace.finish(200)
    assert len(sent) == 2
    llm = sent[1]
    assert llm['run_type'] == 'llm'
    assert llm['inputs'] == {} and llm['outputs'] == {}
    assert llm['extra']['metadata']['usage_metadata']['total_cost'] == pytest.approx(.42)
    assert llm['trace_id'] == trace.id
    client.flush()


def test_langsmith_sdk_paginates_without_sending_global_limit(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from langsmith import Client

    client = Client(api_url='https://langsmith.example.invalid', api_key='test',
                    auto_batch_tracing=False, omit_traced_runtime_info=True)
    project_id = uuid4()
    pages = []
    for page_index in range(2):
        runs = []
        for index in range(100):
            data = record()
            runs.append({'id': data['id'], 'name': 'quimia.chat', 'run_type': 'chain',
                         'start_time': datetime.now(timezone.utc).isoformat(),
                         'extra': {'metadata': {'quimia_sre': data}}})
        pages.append({'runs': runs, 'cursors': {'next': 'page-2'} if page_index == 0 else {}})
    queries = []
    def request(self, method, path, *, request_kwargs, **kwargs):
        assert method == 'POST' and path == '/runs/query'
        body = json.loads(request_kwargs['data'])
        assert 'limit' not in body  # A API rejeita valores maiores que 100.
        queries.append(body)
        return SimpleNamespace(json=lambda: pages[len(queries)-1])
    monkeypatch.setattr(Client, 'request_with_retries', request)
    monkeypatch.setattr(Client, 'read_project', lambda self, **kwargs: SimpleNamespace(id=project_id))
    monkeypatch.setattr(Client, 'list_feedback', lambda self, **kwargs: iter(()))
    monkeypatch.setattr(storage, 'get_client', lambda: client)
    loaded, truncated = storage.records(limit=150)
    assert len(loaded) == 150 and truncated
    assert len(queries) == 2 and queries[1]['cursor'] == 'page-2'
