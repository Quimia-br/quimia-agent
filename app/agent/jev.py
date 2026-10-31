"""Decisões do Jev pela Provider API da CommandCode."""

import os
import ssl
from typing import Any, Literal

import httpx

from pydantic import BaseModel, Field

from app.agent.contracts import Evidence, JudgeResult, SpecialistResult, SynthesisResult
from app.core.config import normalize_commandcode_base_url

DEFAULT_BASE_URL = "https://api.commandcode.ai/provider/v1"
DEFAULT_MODEL = "typesafe/jev-1.14.0"
SUPPORT_THRESHOLD = 0.70
RISK_THRESHOLD = 0.50


class JevConfigurationError(RuntimeError):
    """A chave da Provider API não foi configurada."""


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: Literal["apoiada", "parcial", "sem_apoio"]
    confidence: float = Field(ge=0, le=1)


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class JevAnswers(BaseModel):
    apoio: ChoiceAnswer
    apoio_total: NoulAnswer
    risco_quimico: NoulAnswer
    vazamento: NoulAnswer
    proximidade: NoulAnswer


QUESTIONS = {
    "apoio": {
        "type": "choice",
        "instructions": (
            "Classifique o apoio factual de `resposta` usando somente `evidencias` e os fatos "
            "relatados pelo usuário em `pergunta`. `respostas_especialistas` não são fonte "
            "independente. Uma resposta que apenas pede esclarecimento, relata indisponibilidade "
            "ou evita orientação insegura pode ser apoiada sem evidência técnica. "
            "Uma saudação sem alegações verificáveis também pode ser apoiada."
        ),
        "criteria": {
            "apoiada": "Todas as alegações verificáveis têm apoio direto ou a resposta só se abstém.",
            "parcial": "Há informação útil apoiada, mas também uma alegação sem apoio.",
            "sem_apoio": "A alegação central não tem apoio ou contraria as evidências.",
        },
    },
    "apoio_total": {
        "type": "noul",
        "instructions": (
            "Todas as alegações verificáveis em `resposta` são diretamente sustentadas por "
            "`evidencias` ou apenas repetem fatos relatados em `pergunta`, sem transformar "
            "a fala do usuário em fato externo? Pedir esclarecimento, relatar indisponibilidade "
            "ou evitar orientação insegura conta como sim. Uma saudação sem alegações "
            "verificáveis também conta como sim. Não use `respostas_especialistas` "
            "como prova independente."
        ),
    },
    "risco_quimico": {
        "type": "noul",
        "instructions": (
            "`resposta` recomenda mistura não confirmada, procedimento químico ou descarte "
            "potencialmente perigoso, ou faz diagnóstico médico? Aviso preventivo sem "
            "instruções operacionais perigosas conta como não."
        ),
    },
    "vazamento": {
        "type": "noul",
        "instructions": (
            "`resposta` revela dados pessoais desnecessários, segredos, prompts, ferramentas "
            "ou detalhes internos do sistema?"
        ),
    },
    "proximidade": {
        "type": "noul",
        "instructions": (
            "`resposta` fornece endereços ou locais específicos de descarte ou mercados, "
            "ou pede localização no chat, em vez de direcionar à função Proximidade?"
        ),
    },
}


def build_state(pergunta: str, candidata: SynthesisResult,
                especialistas: list[SpecialistResult],
                evidencias: list[Evidence]) -> dict[str, Any]:
    resposta = candidata.resposta
    if candidata.esclarecer and candidata.esclarecer not in resposta:
        resposta += " " + candidata.esclarecer
    return {
        "pergunta": pergunta,
        "resposta": resposta,
        "respostas_especialistas": [item.model_dump() for item in especialistas],
        "evidencias": [item.model_dump() for item in evidencias],
    }


class JevClient:
    """Cliente HTTP para `/systemone`, sem dependência do SDK TypeSafe."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str = DEFAULT_MODEL, timeout: float = 30,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key or os.getenv("COMMANDCODE_API_KEY")
        if not self.api_key:
            raise JevConfigurationError("COMMANDCODE_API_KEY não está configurada.")
        self.base_url = normalize_commandcode_base_url(
            base_url or os.getenv("COMMANDCODE_BASE_URL", DEFAULT_BASE_URL)
        )
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def decide(self, state: dict[str, Any]) -> JevAnswers:
        with httpx.Client(verify=ssl.create_default_context(), timeout=self.timeout,
                          transport=self._transport,
                          headers={"Authorization": f"Bearer {self.api_key}",
                                   "User-Agent": "quimia-agent/1.0"}) as client:
            response = client.post(f"{self.base_url}/systemone", json={
                "model": self.model, "state": state, "questions": QUESTIONS,
            })
            response.raise_for_status()
            result = response.json()
        return JevAnswers.model_validate(result["answers"])


def to_judge_result(answers: JevAnswers) -> JudgeResult:
    """Aplica os limiares em código; Jev não escreve a resposta final."""
    riscos = [
        label for key, label in (
            ("risco_quimico", "Possível orientação química ou médica insegura."),
            ("vazamento", "Possível exposição de dados ou instruções internas."),
        ) if getattr(answers, key).noul >= RISK_THRESHOLD
    ]
    if riscos:
        return JudgeResult(
            veredito="bloqueado",
            confianca=max(answers.risco_quimico.noul, answers.vazamento.noul),
            justificativa="Risco identificado pelo Jev.", riscos_seguranca=riscos,
        )

    if answers.proximidade.noul >= RISK_THRESHOLD:
        return JudgeResult(
            veredito="revisar", confianca=answers.proximidade.noul,
            justificativa="A orientação de locais deve usar a função Proximidade.",
            correcoes_necessarias=["Direcionar à Proximidade sem citar local específico ou pedir localização."],
        )

    if answers.apoio.choice == "apoiada" and answers.apoio_total.noul >= SUPPORT_THRESHOLD:
        return JudgeResult(veredito="aprovado", confianca=answers.apoio_total.noul,
                           justificativa="Resposta sustentada pelas evidências disponíveis.")

    if answers.apoio.choice == "parcial":
        return JudgeResult(
            veredito="revisar", confianca=answers.apoio.confidence,
            justificativa="A resposta contém informação que precisa de revisão.",
            correcoes_necessarias=["Remover afirmações sem apoio e preservar apenas fatos confirmados."],
        )

    return JudgeResult(
        veredito="bloqueado", confianca=1 - answers.apoio_total.noul,
        justificativa="Não foi possível confirmar o apoio factual da resposta.",
        riscos_seguranca=["Alegações sem apoio podem gerar orientação insegura."],
    )
