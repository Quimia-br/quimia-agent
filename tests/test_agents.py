import asyncio

import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

import app.agent.judge as judge_module
from app.agent.contracts import (
    ChemicalResult,
    Evidence,
    JudgeResult,
    OrchestratorResult,
    RoutePlan,
    SpecialistResult,
    SynthesisResult,
)
from app.agent.judge import JudgeAgent
from app.agent.orchestrator import OrchestratorAgent
from app.agent.specialists.bau_agent import VaultAgent
from app.agent.specialists.gps_agent import GpsAgent
from app.agent.specialists.quimico_agent import ChemicalAgent
from app.agent.synthesizer import SynthesizerAgent


class FakeChatModel:
    def __init__(self, response):
        self.response = response
        self.output_schema = None

    def with_structured_output(self, output_schema):
        self.output_schema = output_schema
        return RunnableLambda(lambda _: self.response)


def test_judge_uses_specialist_model_profile(monkeypatch):
    selected_profiles = []
    model = FakeChatModel({})

    def create_model(profile):
        selected_profiles.append(profile)
        return model

    monkeypatch.setattr(judge_module, "create_chat_model", create_model)

    JudgeAgent()

    assert selected_profiles == [judge_module.ModelProfile.SPECIALIST]


def test_orchestrator_uses_structured_contract():
    model = FakeChatModel(
        {
            "status": "roteado",
            "pergunta_original": "Posso usar este produto em granito?",
            "rotas": [
                {
                    "id": "r1",
                    "agente": "quimico",
                    "objetivo": "Verificar compatibilidade com granito.",
                    "depende_de": [],
                }
            ],
        }
    )

    result = OrchestratorAgent(model=model).invoke(
        "Posso usar este produto em granito?"
    )

    assert isinstance(result, OrchestratorResult)
    assert result.rotas[0].agente == "quimico"


@pytest.mark.parametrize(
    ("agent_class", "domain"),
    [(ChemicalAgent, "quimico"), (VaultAgent, "bau"), (GpsAgent, "gps")],
)
def test_specialists_return_validated_results(agent_class, domain):
    model = FakeChatModel(
        {
            "dominio": domain,
            "intencao": "consultar",
            "resposta": "Não há dados confirmados suficientes.",
        }
    )

    result = agent_class(model=model).invoke("Pergunta", "Consultar o domínio")

    assert isinstance(result, SpecialistResult)
    assert result.dominio == domain


def test_synthesizer_consolidates_structured_inputs():
    model = FakeChatModel({"resposta": "Resposta consolidada."})
    plan = OrchestratorResult(
        status="roteado",
        pergunta_original="Pergunta",
        rotas=[
            RoutePlan(
                id="r1", agente="quimico", objetivo="Consultar", depende_de=[]
            )
        ],
    )
    specialist = ChemicalResult(
        intencao="consultar", resposta="Resultado confirmado."
    )

    result = SynthesizerAgent(model=model).invoke("Pergunta", plan, [specialist])

    assert result == SynthesisResult(resposta="Resposta consolidada.")


def test_judge_evaluates_answer_and_evidence():
    model = FakeChatModel(
        {
            "veredito": "aprovado",
            "confianca": 0.95,
            "justificativa": "A resposta está sustentada pela evidência.",
            "alegacoes_nao_sustentadas": [],
            "riscos_seguranca": [],
            "correcoes_necessarias": [],
        }
    )
    answer = SynthesisResult(resposta="Use conforme o rótulo.")
    specialist = ChemicalResult(
        intencao="consultar", resposta="O rótulo orienta esse uso."
    )
    evidence = Evidence(
        source_id="fds-1",
        title="Ficha de segurança",
        content="Utilizar conforme as instruções do rótulo.",
        page=2,
    )

    result = JudgeAgent(model=model).invoke(
        "Como usar?", answer, [specialist], [evidence]
    )

    assert isinstance(result, JudgeResult)
    assert result.aprovado is True


def test_agent_supports_async_invocation():
    model = FakeChatModel(
        {
            "status": "fora_escopo",
            "pergunta_original": "Conte uma piada",
            "rotas": [],
        }
    )

    result = asyncio.run(OrchestratorAgent(model=model).ainvoke("Conte uma piada"))

    assert result.status == "fora_escopo"


def test_orchestrator_rejects_dependency_on_future_route():
    with pytest.raises(ValidationError):
        OrchestratorResult(
            status="roteado",
            pergunta_original="Pergunta",
            rotas=[
                RoutePlan(
                    id="r1",
                    agente="quimico",
                    objetivo="Consultar",
                    depende_de=["r2"],
                ),
                RoutePlan(
                    id="r2", agente="gps", objetivo="Localizar", depende_de=[]
                ),
            ],
        )


def test_judge_rejects_approved_verdict_with_safety_risk():
    with pytest.raises(ValidationError):
        JudgeResult(
            veredito="aprovado",
            confianca=0.9,
            justificativa="Inconsistente.",
            riscos_seguranca=["Mistura não confirmada."],
        )