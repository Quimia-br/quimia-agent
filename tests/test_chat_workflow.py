import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.agent.contracts import OrchestratorResult, RoutePlan, JudgeResult, SynthesisResult, SpecialistResult, Evidence
from app.agent.workflow import build_graph, SAFE_RESPONSE
import app.main as main
import app.routes.chat_routes as routes


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
    result = asyncio.run(build_graph(orchestrator=Orchestrator(), synthesizer=Synthesizer(), judge=Judge()).ainvoke(
        {"pergunta": "Pergunta", "user_id": str(uuid4()), "contexto": ""}))
    assert result["resposta"] == SAFE_RESPONSE
    assert result["revisoes"] <= 1


def test_chat_swagger_validation_and_response_without_history(monkeypatch):
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    monkeypatch.delenv("CHAT_BACKEND_TOKEN", raising=False)
    calls = []
    monkeypatch.setattr(routes, "save_turn", lambda *args: calls.append(args))
    async def run(question, user):
        assert question == "Pergunta"
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
    def fail(*args): raise RuntimeError("password=secret")
    monkeypatch.setattr(routes, "run_chat", fail)
    with TestClient(main.create_app()) as client:
        response = client.post("/chat", json={"user_id": str(uuid4()), "session_id": "s", "pergunta": "Pergunta"})
    assert response.status_code == 503
    assert "password" not in response.text


