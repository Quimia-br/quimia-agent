import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.agent.contracts import OrchestratorResult, RoutePlan, JudgeResult, SynthesisResult, SpecialistResult, Evidence
from app.agent.workflow import build_graph, SAFE_RESPONSE
from app.agent.guardrails.input_guardrail import InputDecision
import app.main as main
import app.routes.chat_routes as routes
import app.database.chat_history as chat_history
from app.schemas.schemas import ChatRequest


class AllowedInput:
    async def ainvoke(self, question):
        return InputDecision(categoria="permitido", motivo="Pedido permitido")


class PassthroughOutput:
    async def ainvoke(self, question, answer, specialists, evidence):
        return answer


def test_graph_dependencies_evidence_and_revision():
    events = []
    class Orchestrator:
        async def ainvoke(self, question, context):
            events.append("orquestrador")
            return OrchestratorResult(status="roteado", pergunta_original=question, rotas=[
                RoutePlan(id="r1", agente="bau", objetivo="Identificar"),
                RoutePlan(id="r2", agente="quimico", objetivo="Consultar", depende_de=["r1"])])
    class Specialist:
        def __init__(self, name): self.name = name
        async def ainvoke_with_evidence(self, question, goal, context, history):
            events.append(self.name)
            if self.name == "quimico": assert "Produto identificado" in context
            return SpecialistResult(dominio=self.name, intencao="consultar", resposta="Produto identificado"), [
                Evidence(source_id=self.name, title="Tool", content="Evidência confirmada")]
    class Synthesizer:
        async def ainvoke(self, question, plan, results, feedback):
            events.append("sintetizador")
            return SynthesisResult(resposta="Resposta revisada" if feedback != "Não fornecido." else "Candidata")
    class Judge:
        count = 0
        async def ainvoke(self, question, answer, results, evidence):
            events.append("juiz")
            assert len(evidence) == 2
            self.count += 1
            return JudgeResult(veredito="revisar" if self.count == 1 else "aprovado", confianca=1,
                               justificativa="Avaliação", correcoes_necessarias=["Corrigir"] if self.count == 1 else [])
    graph = build_graph(orchestrator=Orchestrator(), synthesizer=Synthesizer(), judge=Judge(),
                        input_guardrail=AllowedInput(), output_guardrail=PassthroughOutput(),
                        factory=lambda name, owner: Specialist(name))
    result = asyncio.run(graph.ainvoke({"pergunta": "Pergunta", "user_id": str(uuid4()), "contexto": "Histórico"}))
    assert events == ["orquestrador", "bau", "quimico", "sintetizador", "juiz", "sintetizador", "juiz"]
    assert result["resposta"] == "Resposta revisada"


@pytest.mark.parametrize("verdict", ["bloqueado", "revisar"])
def test_unapproved_candidate_is_never_delivered(verdict):
    class Orchestrator:
        async def ainvoke(self, question, context):
            return OrchestratorResult(status="fora_escopo", pergunta_original=question)
    class Synthesizer:
        async def ainvoke(self, *args): return SynthesisResult(resposta="Texto que não deve sair")
    class Judge:
        async def ainvoke(self, *args):
            return JudgeResult(veredito=verdict, confianca=1, justificativa="Problema",
                               riscos_seguranca=["Risco"] if verdict == "bloqueado" else [],
                               correcoes_necessarias=["Corrigir"] if verdict == "revisar" else [])
    result = asyncio.run(build_graph(orchestrator=Orchestrator(), synthesizer=Synthesizer(), judge=Judge(),
                                    input_guardrail=AllowedInput(), output_guardrail=PassthroughOutput()).ainvoke(
        {"pergunta": "Pergunta", "user_id": str(uuid4()), "contexto": ""}))
    assert result["resposta"] == SAFE_RESPONSE
    assert result["revisoes"] <= 1


def test_chat_swagger_validation_and_response_with_history(monkeypatch):
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    monkeypatch.delenv("CHAT_BACKEND_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(routes, "save_turn", lambda *args: calls.append(args))
    monkeypatch.setattr(routes, "load_chat_context", lambda user, session: "Turno anterior")
    async def run(question, user, context):
        assert question == "Pergunta"
        assert context == "Turno anterior"
        return "Resposta aprovada"
    monkeypatch.setattr(routes, "run_chat", run)
    owner = str(uuid4())
    payload = {"user_id": owner, "session_id": "session-1", "pergunta": "Pergunta"}
    with TestClient(main.create_app()) as client:
        operation = client.get("/openapi.json").json()["paths"]["/chat"]["post"]
        assert not operation.get("parameters")
        assert not operation.get("security")
        assert client.post("/chat", json={**payload, "pergunta": " "}).status_code == 422
        response = client.post("/chat", json=payload)
    assert response.status_code == 200
    assert response.json() == {"resposta": "Resposta aprovada"}
    assert calls == [(owner, "session-1", "Pergunta", "Resposta aprovada")]


def test_chat_errors_do_not_expose_credentials(monkeypatch):
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    monkeypatch.delenv("CHAT_BACKEND_TOKEN", raising=False)
    monkeypatch.setattr(routes, "load_chat_context", lambda *args: "Não fornecido.")
    def fail(*args): raise RuntimeError("password=secret")
    monkeypatch.setattr(routes, "run_chat", fail)
    with TestClient(main.create_app()) as client:
        response = client.post("/chat", json={"user_id": str(uuid4()), "session_id": "s", "pergunta": "Pergunta"})
    assert response.status_code == 503
    assert "password" not in response.text


def test_chat_context_filters_user_session_orders_and_limits(monkeypatch):
    class Cursor:
        def __init__(self):
            self.rows = [
                {"pergunta": "mais recente", "resposta": "resposta recente"},
                {"pergunta": "mais antiga", "resposta": "resposta antiga"},
            ]
        def sort(self, spec):
            assert spec == [("criado_em", -1), ("_id", -1)]
            return self
        def limit(self, count):
            assert count == chat_history.MAX_TURNS
            return self
        def __iter__(self):
            return iter(self.rows)
    class Collection:
        def find(self, query, projection):
            assert query == {"user_id": "user-1", "session_id": "session-1"}
            assert projection == {"_id": 0, "pergunta": 1, "resposta": 1}
            return Cursor()
    class Database:
        chat_turns = Collection()
    monkeypatch.setattr(chat_history, "get_mongo", lambda: Database())
    context = chat_history.load_chat_context("user-1", "session-1")
    turns = json.loads(context.split("\n", 1)[1])
    assert [turn["pergunta"] for turn in turns] == ["mais antiga", "mais recente"]


def test_chat_context_empty_and_truncated(monkeypatch):
    class Cursor:
        def __init__(self, rows): self.rows = rows
        def sort(self, *_): return self
        def limit(self, *_): return self
        def __iter__(self): return iter(self.rows)
    class Collection:
        rows = []
        def find(self, *_): return Cursor(self.rows)
    class Database:
        chat_turns = Collection()
    db = Database()
    monkeypatch.setattr(chat_history, "get_mongo", lambda: db)
    assert chat_history.load_chat_context("user", "session") == "Não fornecido."
    db.chat_turns.rows = [{"pergunta": "p" * 2000, "resposta": "r" * 4000}]
    context = chat_history.load_chat_context("user", "session")
    turn = json.loads(context.split("\n", 1)[1])[0]
    assert len(turn["pergunta"]) == chat_history.MAX_QUESTION_CHARS
    assert len(turn["resposta"]) == chat_history.MAX_ANSWER_CHARS


def test_chat_route_passes_same_session_history_to_graph_and_saves_reply(monkeypatch):
    owner = uuid4()
    events = []
    def load(user, session):
        events.append(("load", user, session))
        return "Contexto da sessão"
    async def run(question, user, context):
        events.append(("run", question, user, context))
        return "Resposta"
    def save(user, session, question, answer):
        events.append(("save", user, session, question, answer))
    monkeypatch.setattr(routes, "load_chat_context", load)
    monkeypatch.setattr(routes, "run_chat", run)
    monkeypatch.setattr(routes, "save_turn", save)
    response = asyncio.run(routes.conversar(ChatRequest(user_id=owner, session_id="s1", pergunta="E ele?")))
    assert response.resposta == "Resposta"
    assert events == [
        ("load", str(owner), "s1"),
        ("run", "E ele?", str(owner), "Contexto da sessão"),
        ("save", str(owner), "s1", "E ele?", "Resposta"),
    ]


