"""Grafo do Kemi: entrada -> orquestrador -> especialistas -> juiz -> saída -> entrega."""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.contracts import Evidence, SpecialistResult, SynthesisResult
from app.agent.orchestrator import OrchestratorAgent
from app.agent.synthesizer import SynthesizerAgent
from app.agent.judge import JudgeAgent
from app.agent.guardrails.input_guardrail import InputGuardrail, INPUT_SAFE_RESPONSE
from app.agent.guardrails.output_guardrail import OutputGuardrail, OUTPUT_SAFE_RESPONSE
from app.agent.specialists.bau.bau_agent import BauAgent
from app.agent.specialists.quimico.quimico_agent import ChemicalAgent
from app.agent.specialists.faq.faq_agent import FaqAgent
from app.agent.specialists.gps.gps_agent import GpsAgent, GPS_RESPONSE
from app.observability.telemetry import current, mark, stage
from app.observability.callbacks import MetricsCallback

logger = logging.getLogger(__name__)
SAFE_RESPONSE = "Não consegui confirmar uma resposta segura com as informações disponíveis no app. Consulte as orientações do fabricante e não misture produtos sem confirmação."


@dataclass(frozen=True)
class ChatRunResult:
    resposta: str
    agentes_acionados: list[str]


class ChatState(TypedDict, total=False):
    pergunta: str
    user_id: str
    contexto: str
    plano: object
    resultados: list
    evidencias: list
    candidata: object
    vereditos: list
    revisada: object
    resposta: str
    entrada_permitida: bool
    agentes_acionados: list[str]


def specialist_factory(name, user_id):
    if name == "bau":
        return BauAgent(user_id=user_id)
    return {"quimico": ChemicalAgent, "faq": FaqAgent, "gps": GpsAgent}[name]()


def build_graph(*, orchestrator=None, synthesizer=None, judge=None,
                input_guardrail=None, output_guardrail=None, factory=specialist_factory):
    @stage("guardrail_entrada")
    async def check_input(state):
        try:
            decision = await (input_guardrail or InputGuardrail()).ainvoke(state["pergunta"])
            allowed = decision.permitido
            if not allowed:
                mark(outcome="bloqueado_entrada")
                logger.warning("Guardrail de entrada recusou a mensagem: categoria=%s", decision.categoria)
        except Exception:
            logger.exception("Falha no guardrail de entrada")
            raise
        return {"entrada_permitida": allowed,
                "agentes_acionados": [*state.get("agentes_acionados", []), "guardrail_entrada"],
                **({} if allowed else {"resposta": INPUT_SAFE_RESPONSE})}

    def route_input(state):
        return "orquestrador" if state["entrada_permitida"] else "encerrar"

    @stage("orquestrador")
    async def orchestrate(state):
        plan = await (orchestrator or OrchestratorAgent()).ainvoke(state["pergunta"], state["contexto"])
        if plan.pergunta_original != state["pergunta"]:
            raise ValueError("O orquestrador alterou a pergunta original.")
        mark(route=",".join(route.agente for route in plan.rotas) or plan.status)
        if not plan.rotas:
            mark(outcome=plan.status)
        return {"plano": plan,
                "agentes_acionados": [*state["agentes_acionados"], "orquestrador"]}

    def route_plan(state):
        return "especialistas" if state["plano"].rotas else "resposta_orquestrador"

    def direct_answer(state):
        return {"candidata": SynthesisResult(resposta=state["plano"].resposta)}

    @stage("especialistas")
    async def specialists(state):
        pending = list(state["plano"].rotas)
        completed = {}
        evidence = []

        @stage(lambda route: route.agente, kind="agent")
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
                raise

        while pending:
            ready = [route for route in pending if all(key in completed for key in route.depende_de)]
            if not ready:
                raise ValueError("Dependências de rotas inválidas.")
            tasks = [asyncio.create_task(run(route)) for route in ready]
            try:
                outputs = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            for route, (result, sources) in zip(ready, outputs):
                if result.dominio != route.agente:
                    raise ValueError("Domínio inesperado do especialista.")
                completed[route.id] = result
                evidence.extend(source.model_copy(update={"source_id": f"{route.id}:{source.source_id}"})
                                for source in sources)
                pending.remove(route)
        return {"resultados": [completed[route.id] for route in state["plano"].rotas],
                "evidencias": evidence,
                "agentes_acionados": [*state["agentes_acionados"],
                                      *(route.agente for route in state["plano"].rotas)]}

    @stage("juiz")
    async def evaluate(state):
        verdicts = []
        for route, result in zip(state["plano"].rotas, state["resultados"]):
            scoped_evidence = [source for source in state["evidencias"]
                               if source.source_id.startswith(f"{route.id}:")]
            answer = SynthesisResult(resposta=result.resposta, esclarecer=result.esclarecer)
            verdicts.append(await (judge or JudgeAgent()).ainvoke(
                state["pergunta"], answer, [result], scoped_evidence))
        if all(verdict.aprovado for verdict in verdicts):
            trace = current.get()
            if trace and trace.outcome == "desconhecido":
                mark(outcome="esclarecer" if any(r.esclarecer for r in state["resultados"]) else "respondido")
            parts = []
            for result in state["resultados"]:
                part = result.resposta
                if result.esclarecer and result.esclarecer not in part:
                    part += " " + result.esclarecer
                parts.append(part)
            candidate = SynthesisResult(resposta="\n\n".join(parts))
        else:
            mark(outcome="nao_aprovado")
            candidate = SynthesisResult(resposta=SAFE_RESPONSE)
        return {"vereditos": verdicts, "candidata": candidate,
                "agentes_acionados": [*state["agentes_acionados"],
                                      *(["juiz"] * len(verdicts))]}

    @stage("guardrail_saida")
    async def check_output(state):
        try:
            answer = await (output_guardrail or OutputGuardrail()).ainvoke(
                state["pergunta"], state["candidata"],
                state.get("resultados", []), state.get("evidencias", []))
        except Exception:
            mark(degraded=True)
            logger.exception("Falha no guardrail de saída")
            answer = SynthesisResult(resposta=OUTPUT_SAFE_RESPONSE)
        return {"revisada": answer,
                "agentes_acionados": [*state["agentes_acionados"], "guardrail_saida"]}

    @stage("sintetizador")
    async def synthesize(state):
        answer = await (synthesizer or SynthesizerAgent()).ainvoke(state["revisada"])
        if answer != state["revisada"]:
            raise ValueError("O sintetizador alterou a resposta revisada.")
        return {"resposta": answer.resposta,
                "agentes_acionados": [*state["agentes_acionados"], "sintetizador"]}

    graph = StateGraph(ChatState)
    for name, node in [("guardrail_entrada", check_input), ("orquestrador", orchestrate),
                       ("resposta_orquestrador", direct_answer), ("especialistas", specialists),
                       ("juiz", evaluate), ("guardrail_saida", check_output),
                       ("sintetizador", synthesize)]:
        graph.add_node(name, node)
        
    graph.add_edge(START, "guardrail_entrada")
    graph.add_conditional_edges("guardrail_entrada", route_input,
                                {"orquestrador": "orquestrador", "encerrar": END})
    graph.add_conditional_edges("orquestrador", route_plan,
                                {"especialistas": "especialistas",
                                 "resposta_orquestrador": "resposta_orquestrador"})
    graph.add_edge("especialistas", "juiz")
    graph.add_edge("juiz", "guardrail_saida")
    graph.add_edge("resposta_orquestrador", "guardrail_saida")
    graph.add_edge("guardrail_saida", "sintetizador")
    graph.add_edge("sintetizador", END)
    return graph.compile()


async def run_chat(pergunta, user_id, contexto="Não fornecido."):
    trace = current.get()
    config = {"callbacks": [MetricsCallback(trace)]} if trace else {}
    result = await build_graph().ainvoke(
        {"pergunta": pergunta, "user_id": user_id, "contexto": contexto}, config=config)
    return ChatRunResult(resposta=result["resposta"], agentes_acionados=result["agentes_acionados"])
