"""Grafo do Kemi: orquestrador -> especialistas -> sintetizador -> juiz."""
import asyncio
import json
import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.contracts import Evidence, SpecialistResult
from app.agent.orchestrator import OrchestratorAgent
from app.agent.synthesizer import SynthesizerAgent
from app.agent.judge import JudgeAgent
from app.agent.specialists.bau.bau_agent import BauAgent
from app.agent.specialists.quimico.quimico_agent import ChemicalAgent
from app.agent.specialists.faq.faq_agent import FaqAgent
from app.agent.specialists.gps.gps_agent import GpsAgent, GPS_RESPONSE

logger = logging.getLogger(__name__)
SAFE_RESPONSE = "Não consegui confirmar uma resposta segura com as informações disponíveis no app. Consulte as orientações do fabricante e não misture produtos sem confirmação."


class ChatState(TypedDict, total=False):
    pergunta: str
    user_id: str
    contexto: str
    plano: object
    resultados: list
    evidencias: list
    candidata: object
    veredito: object
    revisoes: int
    feedback: str
    resposta: str


def specialist_factory(name, user_id):
    if name == "bau":
        return BauAgent(user_id=user_id)
    return {"quimico": ChemicalAgent, "faq": FaqAgent, "gps": GpsAgent}[name]()


def build_graph(*, orchestrator=None, synthesizer=None, judge=None, factory=specialist_factory):
    # Modelos são criados apenas durante uma requisição, nunca ao importar a API.
    async def orchestrate(state):
        plan = await (orchestrator or OrchestratorAgent()).ainvoke(state["pergunta"], state["contexto"])
        if plan.pergunta_original != state["pergunta"]:
            raise ValueError("O orquestrador alterou a pergunta original.")
        return {"plano": plan, "revisoes": 0, "feedback": "Não fornecido."}

    async def specialists(state):
        pending = list(state["plano"].rotas)
        completed = {}
        evidence = []

        async def run(route):
            dependencies = [completed[key] for key in route.depende_de]
            if any(item.esclarecer for item in dependencies):
                return SpecialistResult(dominio=route.agente, intencao="consultar",
                                        resposta="É necessário esclarecer a identificação antes desta consulta.",
                                        esclarecer=next(item.esclarecer for item in dependencies if item.esclarecer)), []
            try:
                agent = factory(route.agente, state["user_id"])
                if route.agente == "faq":
                    return await agent.ainvoke_with_evidence(state["pergunta"], route.objetivo)
                context = json.dumps([item.model_dump() for item in dependencies], ensure_ascii=False)
                if route.agente == "gps":
                    result = await agent.ainvoke(state["pergunta"], route.objetivo)
                    return result, [Evidence(source_id="gps:orientation", title="Orientação padrão de descarte", content=GPS_RESPONSE)]
                return await agent.ainvoke_with_evidence(state["pergunta"], route.objetivo, context, state["contexto"])
            except Exception:
                logger.exception("Falha no especialista %s", route.agente)
                return SpecialistResult(dominio=route.agente, intencao="consultar",
                                        resposta="Não foi possível consultar essas informações agora."), []

        while pending:
            ready = [route for route in pending if all(key in completed for key in route.depende_de)]
            if not ready:
                raise ValueError("Dependências de rotas inválidas.")
            outputs = await asyncio.gather(*(run(route) for route in ready))
            for route, (result, sources) in zip(ready, outputs):
                if result.dominio != route.agente:
                    raise ValueError("Domínio inesperado do especialista.")
                completed[route.id] = result
                evidence.extend(source.model_copy(update={"source_id": f"{route.id}:{source.source_id}"})
                                for source in sources)
                pending.remove(route)
        return {"resultados": [completed[route.id] for route in state["plano"].rotas], "evidencias": evidence}

    async def synthesize(state):
        answer = await (synthesizer or SynthesizerAgent()).ainvoke(
            state["pergunta"], state["plano"], state["resultados"], state["feedback"])
        return {"candidata": answer}

    async def evaluate(state):
        verdict = await (judge or JudgeAgent()).ainvoke(
            state["pergunta"], state["candidata"], state["resultados"], state["evidencias"])
        return {"veredito": verdict}

    def decide(state):
        if state["veredito"].veredito == "revisar" and state["revisoes"] < 1:
            return "revisar"
        return "finalizar"

    def revise(state):
        return {"revisoes": state["revisoes"] + 1, "feedback": state["veredito"].model_dump_json()}

    def finish(state):
        answer = state["candidata"]
        if not state["veredito"].aprovado:
            return {"resposta": SAFE_RESPONSE}
        text = answer.resposta
        if answer.esclarecer and answer.esclarecer not in text:
            text += " " + answer.esclarecer
        return {"resposta": text}

    graph = StateGraph(ChatState)
    for name, node in [("orquestrador", orchestrate), ("especialistas", specialists),
                       ("sintetizador", synthesize), ("juiz", evaluate), ("revisar", revise), ("finalizar", finish)]:
        graph.add_node(name, node)
    graph.add_edge(START, "orquestrador")
    graph.add_edge("orquestrador", "especialistas")
    graph.add_edge("especialistas", "sintetizador")
    graph.add_edge("sintetizador", "juiz")
    graph.add_conditional_edges("juiz", decide, {"revisar": "revisar", "finalizar": "finalizar"})
    graph.add_edge("revisar", "sintetizador")
    graph.add_edge("finalizar", END)
    return graph.compile()


async def run_chat(pergunta, user_id, contexto="Não fornecido."):
    result = await build_graph().ainvoke({"pergunta": pergunta, "user_id": user_id, "contexto": contexto})
    return result["resposta"]
