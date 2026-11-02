"""Etapas independentes rodam juntas, o /chat respeita o orçamento de tempo e as conexões são reaproveitadas.

A concorrência é provada por eventos (cada lado só termina se o outro começou), não por cronômetro.
"""
import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import BaseModel
from psycopg2.pool import PoolError

import app.agent.llms as llms
import app.database.postgres as postgres
import app.main as main
import app.routes.chat_routes as routes
from app.agent.contracts import JudgeResult, OrchestratorResult, RoutePlan, SpecialistResult, SynthesisResult
from app.agent.guardrails.input_guardrail import INPUT_SAFE_RESPONSE, InputDecision
from app.agent.specialists import sql_tools
from app.agent.specialists.tool_agent import ToolAgent
from app.agent.workflow import ChatRunResult, build_graph
from app.schemas.schemas import ChatRequest

ESTADO = {"pergunta": "Pergunta", "user_id": str(uuid4()), "contexto": ""}
ESPERA = 2


class Sintetizador:
    async def ainvoke(self, revisada):
        return revisada


class SaidaLivre:
    async def ainvoke(self, pergunta, candidata, especialistas, evidencias):
        return candidata


def test_guardrail_de_entrada_e_orquestrador_rodam_ao_mesmo_tempo():
    guardrail_iniciou, orquestrador_iniciou = asyncio.Event(), asyncio.Event()

    class Guardrail:
        async def ainvoke(self, pergunta):
            guardrail_iniciou.set()
            await asyncio.wait_for(orquestrador_iniciou.wait(), ESPERA)  # só segue se o outro já começou
            return InputDecision(categoria="permitido", motivo="ok")

    class Orquestrador:
        async def ainvoke(self, pergunta, contexto):
            orquestrador_iniciou.set()
            await asyncio.wait_for(guardrail_iniciou.wait(), ESPERA)
            return OrchestratorResult(status="saudacao", pergunta_original=pergunta, resposta="Olá!")

    class Juiz:
        async def ainvoke(self, *args):
            raise AssertionError("Saudação não passa pelo juiz")

    resultado = asyncio.run(build_graph(
        input_guardrail=Guardrail(), orchestrator=Orquestrador(), synthesizer=Sintetizador(),
        output_guardrail=SaidaLivre(), judge=Juiz()).ainvoke(dict(ESTADO)))

    assert resultado["resposta"] == "Olá!"
    assert resultado["agentes_acionados"] == ["guardrail_entrada", "orquestrador", "guardrail_saida", "sintetizador"]


def test_mensagem_recusada_descarta_o_plano_e_nenhum_especialista_roda():
    plano_cancelado = []
    plano_iniciou = asyncio.Event()

    class Guardrail:
        async def ainvoke(self, pergunta):
            await asyncio.wait_for(plano_iniciou.wait(), ESPERA)  # o plano já está em andamento quando o veredito sai
            return InputDecision(categoria="prompt_injection", motivo="Tenta mudar as regras")

    class Orquestrador:
        async def ainvoke(self, pergunta, contexto):
            plano_iniciou.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                plano_cancelado.append(True)
                raise

    def fabrica(nome, usuario):
        raise AssertionError("Nenhum especialista pode rodar para uma mensagem recusada")

    resultado = asyncio.run(build_graph(
        input_guardrail=Guardrail(), orchestrator=Orquestrador(), factory=fabrica).ainvoke(dict(ESTADO)))

    assert resultado["resposta"] == INPUT_SAFE_RESPONSE
    assert resultado["agentes_acionados"] == ["guardrail_entrada"]
    assert plano_cancelado == [True]


def test_falha_do_guardrail_cancela_o_plano_e_propaga_o_erro():
    plano_cancelado = []
    plano_iniciou = asyncio.Event()

    class Guardrail:
        async def ainvoke(self, pergunta):
            await asyncio.wait_for(plano_iniciou.wait(), ESPERA)
            raise RuntimeError("provedor fora do ar")

    class Orquestrador:
        async def ainvoke(self, pergunta, contexto):
            plano_iniciou.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                plano_cancelado.append(True)
                raise

    with pytest.raises(RuntimeError, match="provedor fora do ar"):
        asyncio.run(build_graph(input_guardrail=Guardrail(), orchestrator=Orquestrador()).ainvoke(dict(ESTADO)))
    assert plano_cancelado == [True]


def test_juiz_avalia_as_rotas_ao_mesmo_tempo():
    iniciadas = []
    todas_iniciaram = asyncio.Event()

    class Orquestrador:
        async def ainvoke(self, pergunta, contexto):
            return OrchestratorResult(status="roteado", pergunta_original=pergunta, rotas=[
                RoutePlan(id="r1", agente="faq", objetivo="A"), RoutePlan(id="r2", agente="quimico", objetivo="B")])

    class Especialista:
        def __init__(self, nome):
            self.nome = nome

        async def ainvoke_with_evidence(self, *args):
            return SpecialistResult(dominio=self.nome, intencao="consultar", resposta=f"Resposta {self.nome}"), []

        async def ainvoke(self, *args):
            return await self.ainvoke_with_evidence(*args)

    class Juiz:
        async def ainvoke(self, pergunta, resposta, resultados, evidencias):
            iniciadas.append(resposta.resposta)
            if len(iniciadas) == 2:
                todas_iniciaram.set()
            await asyncio.wait_for(todas_iniciaram.wait(), ESPERA)  # só termina se a outra avaliação já começou
            return JudgeResult(veredito="aprovado", confianca=1, justificativa="ok")

    resultado = asyncio.run(build_graph(
        input_guardrail=SimpleNamespace(ainvoke=lambda p: _permitido()), orchestrator=Orquestrador(),
        synthesizer=Sintetizador(), output_guardrail=SaidaLivre(), judge=Juiz(),
        factory=lambda nome, usuario: Especialista(nome)).ainvoke(dict(ESTADO)))

    assert sorted(iniciadas) == ["Resposta faq", "Resposta quimico"]
    assert resultado["resposta"] == "Resposta faq\n\nResposta quimico"  # a ordem das rotas é a do plano
    assert resultado["agentes_acionados"].count("juiz") == 2


async def _permitido():
    return InputDecision(categoria="permitido", motivo="ok")


class Esquema(BaseModel):
    ok: bool


def test_ferramentas_da_mesma_rodada_rodam_juntas_e_voltam_na_ordem():
    barreira = threading.Barrier(2, timeout=ESPERA)  # as duas precisam estar executando ao mesmo tempo

    @tool
    def primeira() -> dict:
        """Primeira consulta."""
        barreira.wait()
        return {"status": "ok", "valor": 1}

    @tool
    def segunda() -> dict:
        """Segunda consulta."""
        barreira.wait()
        return {"status": "ok", "valor": 2}

    class Ligado:
        def __init__(self):
            self.rodadas = 0

        def invoke(self, mensagens):
            self.rodadas += 1
            if self.rodadas == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "primeira", "args": {}, "id": "a"}, {"name": "segunda", "args": {}, "id": "b"}])
            return AIMessage(content="pronto")

    class Modelo:
        def bind_tools(self, ferramentas):
            return Ligado()

        def with_structured_output(self, esquema):
            return SimpleNamespace(invoke=lambda mensagens: Esquema(ok=True))

    resultado, evidencias = ToolAgent(Modelo(), [primeira, segunda], "prompt", Esquema).invoke_with_evidence({})

    assert resultado == Esquema(ok=True)
    assert [e.title for e in evidencias] == ["primeira", "segunda"]
    assert [e.content for e in evidencias] == ['{"status": "ok", "valor": 1}', '{"status": "ok", "valor": 2}']


def test_ferramenta_com_erro_nao_derruba_as_outras_da_rodada():
    @tool
    def boa() -> dict:
        """Consulta que funciona."""
        return {"status": "ok"}

    @tool
    def ruim() -> dict:
        """Consulta que falha."""
        raise RuntimeError("banco fora do ar")

    agente = ToolAgent(SimpleNamespace(), [boa, ruim], "prompt", Esquema)

    resultados = agente._run_tools([{"name": "ruim", "args": {}, "id": "1"}, {"name": "boa", "args": {}, "id": "2"},
                                    {"name": "inexistente", "args": {}, "id": "3"}])

    assert [r["status"] for r in resultados] == ["error", "ok", "error"]
    assert resultados[2]["message"] == "Tool não autorizada."


def _config(orcamento):
    return SimpleNamespace(chat_budget_seconds=orcamento)


def test_chat_acima_do_orcamento_responde_504_em_json(monkeypatch):
    async def lento(pergunta, usuario, contexto, sessao):
        await asyncio.sleep(5)

    monkeypatch.setattr(routes, "load_chat_context", lambda usuario, sessao: "Não fornecido.")
    monkeypatch.setattr(routes, "run_chat", lento)
    monkeypatch.setattr(routes, "carregar_config", lambda: _config(0.05))
    salvos = []
    monkeypatch.setattr(routes, "save_turn", lambda *args: salvos.append(args))
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)

    with TestClient(main.create_app()) as client:
        resposta = client.post("/chat", json={"user_id": str(uuid4()), "session_id": "s", "pergunta": "Pergunta"})

    assert resposta.status_code == 504
    assert resposta.headers["content-type"].startswith("application/json")
    assert "demorou" in resposta.json()["detail"]
    assert salvos == []


def test_turno_e_gravado_depois_da_resposta_e_falha_de_gravacao_nao_afeta_o_usuario(monkeypatch):
    ordem = []

    async def rapido(pergunta, usuario, contexto, sessao):
        ordem.append("run")
        return ChatRunResult("Resposta", ["orquestrador"])

    def gravar(*args):
        ordem.append("save")
        raise RuntimeError("mongo fora do ar")

    monkeypatch.setattr(routes, "load_chat_context", lambda usuario, sessao: "Não fornecido.")
    monkeypatch.setattr(routes, "run_chat", rapido)
    monkeypatch.setattr(routes, "save_turn", gravar)
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)

    with TestClient(main.create_app()) as client:
        resposta = client.post("/chat", json={"user_id": str(uuid4()), "session_id": "s", "pergunta": "Pergunta"})

    assert resposta.status_code == 200
    assert resposta.json()["resposta"] == "Resposta"
    assert ordem == ["run", "save"]


def test_erro_interno_continua_503_em_json(monkeypatch):
    async def quebrado(pergunta, usuario, contexto, sessao):
        raise RuntimeError("segredo interno")

    monkeypatch.setattr(routes, "load_chat_context", lambda usuario, sessao: "Não fornecido.")
    monkeypatch.setattr(routes, "run_chat", quebrado)
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)

    with TestClient(main.create_app()) as client:
        resposta = client.post("/chat", json={"user_id": str(uuid4()), "session_id": "s", "pergunta": "Pergunta"})

    assert resposta.status_code == 503
    assert "segredo" not in resposta.text


# ---- pool do PostgreSQL

class ConexaoFalsa:
    def __init__(self):
        self.closed = 0
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class PoolFalso:
    def __init__(self, conexao, recusas=0):
        self.conexao = conexao
        self.recusas = recusas
        self.devolvidas = []

    def getconn(self):
        if self.recusas:
            self.recusas -= 1
            raise PoolError("connection pool exhausted")
        return self.conexao

    def putconn(self, conexao, close=False):
        self.devolvidas.append(close)


def test_conexao_volta_ao_pool_sem_transacao_aberta(monkeypatch):
    conexao, pool = ConexaoFalsa(), PoolFalso(ConexaoFalsa())
    pool.conexao = conexao
    monkeypatch.setattr(postgres, "_obter_pool", lambda: pool)

    with postgres.get_pg() as entregue:
        assert entregue is conexao

    assert conexao.rollbacks == 1
    assert pool.devolvidas == [False]


def test_conexao_quebrada_e_descartada_em_vez_de_reaproveitada(monkeypatch):
    conexao = ConexaoFalsa()
    pool = PoolFalso(conexao)
    monkeypatch.setattr(postgres, "_obter_pool", lambda: pool)

    with pytest.raises(psycopg2.OperationalError):
        with postgres.get_pg():
            raise psycopg2.OperationalError("server closed the connection unexpectedly")

    assert pool.devolvidas == [True]


def test_pool_esgotado_espera_uma_vaga_antes_de_falhar(monkeypatch):
    conexao = ConexaoFalsa()
    pool = PoolFalso(conexao, recusas=3)
    monkeypatch.setattr(postgres, "_obter_pool", lambda: pool)

    with postgres.get_pg() as entregue:
        assert entregue is conexao

    pool = PoolFalso(conexao, recusas=10_000)
    monkeypatch.setattr(postgres, "_obter_pool", lambda: pool)
    monkeypatch.setattr(postgres, "ESPERA_POR_CONEXAO_SEGUNDOS", 0.1)
    with pytest.raises(PoolError):
        with postgres.get_pg():
            pass


def test_consulta_repete_uma_vez_quando_a_conexao_do_pool_estava_morta(monkeypatch):
    tentativas = []

    def executar(sql, params):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        return [{"id": 1}]

    monkeypatch.setattr(sql_tools, "_executar", executar)

    assert sql_tools.query("SELECT 1") == {"status": "ok", "dados": [{"id": 1}], "encontrado": True}
    assert len(tentativas) == 2


def test_consulta_que_falha_duas_vezes_devolve_erro_sem_detalhes(monkeypatch):
    def executar(sql, params):
        raise psycopg2.OperationalError("senha=segredo")

    monkeypatch.setattr(sql_tools, "_executar", executar)

    resultado = sql_tools.query("SELECT 1")

    assert resultado["status"] == "error"
    assert "segredo" not in str(resultado)


# ---- clientes de IA reaproveitados

def test_modelo_de_chat_e_reaproveitado_enquanto_a_configuracao_nao_muda(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_API_KEY", "chave-de-teste")
    monkeypatch.setenv("COMMANDCODE_MODEL", "modelo-a")
    monkeypatch.setenv("COMMANDCODE_MODEL_FALLBACK", "modelo-b")
    criados = []

    class Falso:
        def __init__(self, **kwargs):
            criados.append(kwargs["model"])

    monkeypatch.setattr(llms, "ChatOpenAI", Falso)
    llms._modelo.cache_clear()

    primeiro, segundo = llms.create_chat_model(), llms.create_chat_model()
    assert primeiro is segundo
    assert criados == ["modelo-a", "modelo-b"]

    monkeypatch.setenv("COMMANDCODE_MODEL", "modelo-c")
    assert llms.create_chat_model() is not primeiro


def test_esforco_de_raciocinio_vai_ao_provedor_so_quando_configurado(monkeypatch):
    monkeypatch.setenv("COMMANDCODE_API_KEY", "chave-de-teste")
    monkeypatch.setenv("COMMANDCODE_MODEL", "modelo-a")
    monkeypatch.setenv("COMMANDCODE_MODEL_FALLBACK", "modelo-b")
    criados = []

    class Falso:
        def __init__(self, **kwargs):
            criados.append(kwargs)

    monkeypatch.setattr(llms, "ChatOpenAI", Falso)

    monkeypatch.setenv("COMMANDCODE_REASONING_EFFORT", "low")
    llms._modelo.cache_clear()
    llms.create_chat_model()
    assert [c.get("reasoning_effort") for c in criados] == ["low", "low"]

    criados.clear()
    monkeypatch.setenv("COMMANDCODE_REASONING_EFFORT", "")
    llms._modelo.cache_clear()
    llms.create_chat_model()
    assert all("reasoning_effort" not in c for c in criados)


def test_orientacao_de_descarte_e_entregue_como_texto_padrao_sem_chamar_a_ia():
    from app.agent.specialists.gps.gps_agent import GPS_RESPONSE

    class Orquestrador:
        async def ainvoke(self, pergunta, contexto):
            return OrchestratorResult(status="roteado", pergunta_original=pergunta,
                                      rotas=[RoutePlan(id="r1", agente="gps", objetivo="Orientar o descarte")])

    class Juiz:
        async def ainvoke(self, pergunta, resposta, resultados, evidencias):
            assert resposta.resposta == GPS_RESPONSE
            assert [e.content for e in evidencias] == [GPS_RESPONSE]  # a evidência sustenta a resposta palavra por palavra
            return JudgeResult(veredito="aprovado", confianca=1, justificativa="ok")

    def fabrica(nome, usuario):
        raise AssertionError("O descarte não passa por um agente de IA")

    resultado = asyncio.run(build_graph(
        input_guardrail=SimpleNamespace(ainvoke=lambda p: _permitido()), orchestrator=Orquestrador(),
        synthesizer=Sintetizador(), output_guardrail=SaidaLivre(), judge=Juiz(), factory=fabrica).ainvoke(dict(ESTADO)))

    assert resultado["resposta"] == GPS_RESPONSE
    assert resultado["agentes_acionados"] == ["guardrail_entrada", "orquestrador", "gps", "juiz",
                                              "guardrail_saida", "sintetizador"]


def test_aplicacao_sobe_com_pool_de_threads_proprio_e_configuravel(monkeypatch):
    import asyncio

    from app import main

    async def sobe():
        async with main.lifespan(main.app):
            loop = asyncio.get_running_loop()
            await asyncio.to_thread(lambda: None)  # o executor só nasce no primeiro uso
            return loop._default_executor._max_workers

    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    assert asyncio.run(sobe()) == int(main.THREADS_PADRAO)

    monkeypatch.setenv("AGENT_THREADS", "7")
    assert asyncio.run(sobe()) == 7
