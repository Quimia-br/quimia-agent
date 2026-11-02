import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from app.agent.contracts import JudgeResult, OrchestratorResult, RoutePlan, SpecialistResult
from app.agent.workflow import build_graph
from app.memory import tools as memory_tools
from tests.test_chat_workflow import AllowedInput, PassthroughOutput


def test_memory_tool_scopes_user_excludes_current_session_and_ranks(monkeypatch):
    class Cursor:
        def sort(self, spec):
            assert spec == [("criado_em", -1), ("_id", -1)]
            return self

        def limit(self, count):
            assert count == memory_tools.MAX_CANDIDATES
            return self

        def __iter__(self):
            return iter([
                {"session_id": "other-1", "resumo": "O usuário falou de mistura.",
                 "criado_em": datetime(2026, 1, 2, tzinfo=timezone.utc)},
                {"session_id": "other-2", "resumo": "O usuário relatou descarte de cândida no ponto Centro.",
                 "criado_em": datetime(2026, 1, 1, tzinfo=timezone.utc)},
            ])

    class Collection:
        def find(self, query, projection):
            assert query == {"user_id": "user-1", "session_id": {"$ne": "current"}}
            assert projection == {"_id": 0, "session_id": 1, "resumo": 1, "criado_em": 1}
            return Cursor()

    class Database:
        chat_summaries = Collection()

    monkeypatch.setattr(memory_tools, "get_mongo", lambda: Database())
    hits = memory_tools.buscar_resumos_conversas.invoke({
        "user_id": "user-1", "session_id": "current",
        "pergunta": "Em qual ponto descartei a cândida?",
    })
    assert [hit["session_id"] for hit in hits] == ["other-2"]
    recent = memory_tools.buscar_resumos_conversas.invoke({
        "user_id": "user-1", "session_id": "current",
        "pergunta": "Qual foi minha conversa anterior?",
    })
    assert recent[0]["session_id"] == "other-1"


def test_memory_tool_uses_previous_day_for_ontem(monkeypatch):
    yesterday = datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)

    class Cursor:
        def sort(self, _): return self
        def limit(self, _): return self
        def __iter__(self):
            return iter([
                {"session_id": "today", "resumo": "Conversa recente", "criado_em": datetime.now(timezone.utc)},
                {"session_id": "yesterday", "resumo": "Conversa de ontem", "criado_em": yesterday},
            ])

    class Collection:
        def find(self, *_): return Cursor()

    class Database:
        chat_summaries = Collection()

    monkeypatch.setattr(memory_tools, "get_mongo", lambda: Database())
    hits = memory_tools.buscar_resumos_conversas.invoke({
        "user_id": "user-1", "session_id": "current",
        "pergunta": "Lembra da conversa de ontem?",
    })
    assert [hit["session_id"] for hit in hits] == ["yesterday"]


def test_memory_only_question_uses_selected_summary(monkeypatch):
    class Orchestrator:
        async def ainvoke(self, question, context):
            return OrchestratorResult(status="memoria", pergunta_original=question,
                                      buscar_memoria=True)

    class Search:
        def invoke(self, args):
            assert args["session_id"] == "current"
            return [{"session_id": "old", "resumo": "O usuário mencionou o ponto Centro."}]

    result = asyncio.run(build_graph(
        orchestrator=Orchestrator(), input_guardrail=AllowedInput(),
        output_guardrail=PassthroughOutput(), memory_search=Search(),
    ).ainvoke({"pergunta": "De qual ponto falei antes?", "user_id": str(uuid4()),
               "session_id": "current", "contexto": "Não fornecido."}))
    assert result["resposta"] == ("Encontrei este resumo de uma conversa anterior: "
                                   "O usuário mencionou o ponto Centro.")
    assert "buscar_memoria" in result["agentes_acionados"]


def test_memory_reaches_specialist_and_judge():
    class Orchestrator:
        async def ainvoke(self, question, context):
            return OrchestratorResult(status="roteado", pergunta_original=question,
                                      buscar_memoria=True,
                                      rotas=[RoutePlan(id="r1", agente="quimico", objetivo="Consultar")])

    class Search:
        def invoke(self, args):
            return [{"session_id": "old", "resumo": "O usuário mencionou cândida."}]

    class Specialist:
        async def ainvoke_with_evidence(self, question, goal, dependencies, context):
            assert "O usuário mencionou cândida." in context
            return SpecialistResult(dominio="quimico", intencao="consultar",
                                    resposta="Você mencionou cândida."), []

    class Judge:
        async def ainvoke(self, question, answer, results, evidence):
            assert len(evidence) == 1
            assert evidence[0].content == "O usuário mencionou cândida."
            return JudgeResult(veredito="aprovado", confianca=1, justificativa="OK")

    result = asyncio.run(build_graph(
        orchestrator=Orchestrator(), input_guardrail=AllowedInput(),
        output_guardrail=PassthroughOutput(), memory_search=Search(), judge=Judge(),
        factory=lambda name, user_id: Specialist(),
    ).ainvoke({"pergunta": "O que mencionei antes?", "user_id": str(uuid4()),
               "session_id": "current", "contexto": "Não fornecido."}))
    assert result["resposta"] == "Você mencionou cândida."
