"""Grafo do Kemi: entrada (guardrail e orquestrador juntos) -> especialistas -> juiz -> saída -> entrega."""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.contracts import Evidence, GpsResult, SpecialistResult, SynthesisResult
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
from app.memory.tools import buscar_resumos_conversas

logger = logging.getLogger(__name__)
SAFE_RESPONSE = "Não consegui confirmar uma resposta segura com as informações disponíveis no app. Consulte as orientações do fabricante e não misture produtos sem confirmação."


PARTE_NAO_CONFIRMADA = ("Não consegui confirmar o restante da sua pergunta com as informações disponíveis no app. "
                        "Consulte as orientações do fabricante e não misture produtos sem confirmação.")
FIM_DE_FRASE = re.compile(r"(?<=[.!?])\s+")


def _chave_da_frase(frase):
    return " ".join(re.findall(r"\w+", frase.lower()))


def juntar_partes(partes):
    """Une as respostas das rotas sem repetir frases: um especialista que depende do outro costuma recomeçar pelo
    que o primeiro acabou de dizer. Só frases idênticas saem; nada é reescrito nem acrescentado."""
    vistas, resultado = set(), []
    for parte in partes:
        novas = []
        for frase in FIM_DE_FRASE.split(parte.strip()):
            chave = _chave_da_frase(frase)
            if chave and chave not in vistas:
                vistas.add(chave)
                novas.append(frase)
        if novas:
            resultado.append(" ".join(novas))
    return "\n\n".join(resultado)


@dataclass(frozen=True)
class ChatRunResult:
    resposta: str
    agentes_acionados: list[str]


class ChatState(TypedDict, total=False):
    pergunta: str
    user_id: str
    session_id: str
    contexto: str
    memorias: list[Evidence]
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
                input_guardrail=None, output_guardrail=None, factory=specialist_factory,
                memory_search=buscar_resumos_conversas):
    @stage("guardrail_entrada")
    async def classify_input(state):
        try:
            decision = await (input_guardrail or InputGuardrail()).ainvoke(state["pergunta"])
            allowed = decision.permitido
            if not allowed:
                mark(outcome="bloqueado_entrada")
                logger.warning("Guardrail de entrada recusou a mensagem: categoria=%s", decision.categoria)
        except Exception:
            logger.exception("Falha no guardrail de entrada")
            raise
        return allowed

    @stage("orquestrador")
    async def make_plan(state):
        plan = await (orchestrator or OrchestratorAgent()).ainvoke(state["pergunta"], state["contexto"])
        if plan.pergunta_original != state["pergunta"]:
            # O modelo pode corrigir ortografia ao ecoar a pergunta. A fonte de
            # verdade é a entrada da requisição, usada também pelos especialistas.
            plan = plan.model_copy(update={"pergunta_original": state["pergunta"]})
        mark(route=",".join(route.agente for route in plan.rotas) or plan.status)
        if not plan.rotas:
            mark(outcome=plan.status)
        return plan

    async def cancel(task):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def entry(state):
        """Guardrail de entrada e orquestrador ao mesmo tempo.

        O orquestrador só planeja: não consulta dados nem chama ferramentas, então o plano de uma mensagem recusada
        é simplesmente descartado. Nada com acesso a dados roda antes do veredito do guardrail.
        """
        planning = asyncio.create_task(make_plan(state))
        try:
            allowed = await classify_input(state)
        except BaseException:
            await cancel(planning)
            raise
        if not allowed:
            await cancel(planning)
            return {"entrada_permitida": False, "resposta": INPUT_SAFE_RESPONSE,
                    "agentes_acionados": [*state.get("agentes_acionados", []), "guardrail_entrada"]}
        plan = await planning
        return {"entrada_permitida": True, "plano": plan,
                "agentes_acionados": [*state.get("agentes_acionados", []), "guardrail_entrada", "orquestrador"]}

    def route_entry(state):
        if not state["entrada_permitida"]:
            return "encerrar"
        if state["plano"].buscar_memoria:
            return "buscar_memoria"
        return "especialistas" if state["plano"].rotas else "resposta_orquestrador"

    @stage("buscar_memoria")
    async def search_memory(state):
        try:
            hits = await asyncio.to_thread(memory_search.invoke, {
                "user_id": state["user_id"], "session_id": state.get("session_id", ""),
                "pergunta": state["pergunta"],
            })
        except Exception:
            logger.exception("Falha ao buscar resumos de conversas anteriores")
            mark(degraded=True)
            hits = []
        sources = [Evidence(source_id=f"memory:{hit['session_id']}",
                            title="Resumo de conversa anterior do usuário",
                            content=hit["resumo"])
                   for hit in hits]
        context = state["contexto"]
        if hits:
            context += ("\n\nResumos de outras sessões relatados pelo usuário "
                        "(não comprovam segurança ou fatos externos):\n" +
                        json.dumps(hits, ensure_ascii=False, default=str))
        return {"memorias": sources, "contexto": context,
                "agentes_acionados": [*state["agentes_acionados"], "buscar_memoria"]}

    def route_memory(state):
        return "especialistas" if state["plano"].rotas else "resposta_orquestrador"

    def direct_answer(state):
        if state["plano"].status == "memoria":
            memories = state.get("memorias", [])
            answer = ("Encontrei este resumo de uma conversa anterior: " + memories[0].content
                      if memories else "Não encontrei um resumo de outra conversa sobre isso.")
            return {"candidata": SynthesisResult(resposta=answer), "evidencias": memories}
        return {"candidata": SynthesisResult(resposta=state["plano"].resposta)}

    @stage("especialistas")
    async def specialists(state):
        pending = list(state["plano"].rotas)
        completed = {}
        evidence = [source.model_copy(update={"source_id": f"{route.id}:{source.source_id}"})
                    for route in state["plano"].rotas for source in state.get("memorias", [])]

        @stage(lambda route: route.agente, kind="agent")
        async def run(route):
            dependencies = [completed[key] for key in route.depende_de]
            if any(item.esclarecer for item in dependencies):
                return SpecialistResult(dominio=route.agente, intencao="consultar",
                                        resposta="É necessário esclarecer a identificação antes desta consulta.",
                                        esclarecer=next(item.esclarecer for item in dependencies if item.esclarecer)), []
            try:
                if route.agente == "gps":
                    # A orientação de descarte é um texto padrão e conservador: entregue como está, ela é sustentada
                    # pela própria evidência. Reescrita por IA, o juiz a bloqueava (a IA acrescentava detalhes do
                    # produto que a evidência não traz) e o usuário recebia só a recusa genérica.
                    recalled = state.get("memorias", [])
                    answer = (("Na conversa anterior, você relatou: " + recalled[0].content + "\n\n")
                              if recalled else "") + GPS_RESPONSE
                    return (GpsResult(dominio="gps", intencao="consultar", resposta=answer),
                            [Evidence(source_id="gps:orientation", title="Orientação padrão de descarte",
                                      content=GPS_RESPONSE)])
                agent = factory(route.agente, state["user_id"])
                if route.agente == "faq":
                    if state.get("memorias"):
                        return await agent.ainvoke_with_evidence(
                            state["pergunta"], route.objetivo, state["contexto"])
                    return await agent.ainvoke_with_evidence(state["pergunta"], route.objetivo)
                context = json.dumps([item.model_dump() for item in dependencies], ensure_ascii=False)
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
        judge_agent = judge or JudgeAgent()

        async def judge_route(route, result):
            scoped_evidence = [source for source in state["evidencias"]
                               if source.source_id.startswith(f"{route.id}:")]
            answer = SynthesisResult(resposta=result.resposta, esclarecer=result.esclarecer)
            return await judge_agent.ainvoke(state["pergunta"], answer, [result], scoped_evidence)

        verdicts = list(await asyncio.gather(
            *(judge_route(route, result) for route, result in zip(state["plano"].rotas, state["resultados"]))))
        approved = [result for result, verdict in zip(state["resultados"], verdicts) if verdict.aprovado]
        if approved:
            trace = current.get()
            if trace and trace.outcome == "desconhecido":
                mark(outcome="esclarecer" if any(r.esclarecer for r in approved) else "respondido")
            parts = []
            for result in approved:
                part = result.resposta
                if result.esclarecer and result.esclarecer not in part:
                    part += " " + result.esclarecer
                parts.append(part)
            if len(approved) < len(verdicts):
                # A rota não aprovada sai; as aprovadas continuam valendo, com o aviso de que faltou uma parte.
                mark(outcome="parcial")
                parts.append(PARTE_NAO_CONFIRMADA)
            candidate = SynthesisResult(resposta=juntar_partes(parts))
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
    for name, node in [("entrada", entry), ("buscar_memoria", search_memory),
                       ("resposta_orquestrador", direct_answer), ("especialistas", specialists),
                       ("juiz", evaluate), ("guardrail_saida", check_output),
                       ("sintetizador", synthesize)]:
        graph.add_node(name, node)

    graph.add_edge(START, "entrada")
    graph.add_conditional_edges("entrada", route_entry,
                                {"encerrar": END, "buscar_memoria": "buscar_memoria",
                                 "especialistas": "especialistas",
                                 "resposta_orquestrador": "resposta_orquestrador"})
    graph.add_conditional_edges("buscar_memoria", route_memory,
                                {"especialistas": "especialistas",
                                 "resposta_orquestrador": "resposta_orquestrador"})
    graph.add_edge("especialistas", "juiz")
    graph.add_edge("juiz", "guardrail_saida")
    graph.add_edge("resposta_orquestrador", "guardrail_saida")
    graph.add_edge("guardrail_saida", "sintetizador")
    graph.add_edge("sintetizador", END)
    return graph.compile()


async def run_chat(pergunta, user_id, contexto="Não fornecido.", session_id=""):
    trace = current.get()
    config = {"callbacks": [MetricsCallback(trace)]} if trace else {}
    result = await build_graph().ainvoke(
        {"pergunta": pergunta, "user_id": user_id, "contexto": contexto,
         "session_id": session_id}, config=config)
    return ChatRunResult(resposta=result["resposta"], agentes_acionados=result["agentes_acionados"])
