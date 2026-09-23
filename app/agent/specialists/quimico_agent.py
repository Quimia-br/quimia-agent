from typing import Any

from app.agent.base import StructuredAgent
from app.agent.contracts import ChemicalResult
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import QUIMICO_PROMPT_COMPLETO


class ChemicalAgent:
    """Especialista em produtos químicos, compatibilidade e segurança."""

    def __init__(self, model: Any | None = None) -> None:
        self._agent = StructuredAgent(
            system_prompt=QUIMICO_PROMPT_COMPLETO,
            human_template=(
                "PERGUNTA_ORIGINAL:\n{pergunta_original}\n\n"
                "OBJETIVO_DA_ROTA:\n{objetivo}\n\n"
                "CONTEXTO_CONFIRMADO_PELAS_TOOLS:\n{contexto_confirmado}\n\n"
                "RESUMO_DA_CONVERSA:\n{resumo_conversa}"
            ),
            output_schema=ChemicalResult,
            model=model or create_chat_model(ModelProfile.SPECIALIST),
        )

    def invoke(
        self,
        pergunta_original: str,
        objetivo: str,
        contexto_confirmado: str = "Nenhum dado confirmado disponível.",
        resumo_conversa: str = "Não fornecido.",
    ) -> ChemicalResult:
        payload = {
            "pergunta_original": pergunta_original,
            "objetivo": objetivo,
            "contexto_confirmado": contexto_confirmado,
            "resumo_conversa": resumo_conversa,
        }
        return self._agent.invoke(payload)

    async def ainvoke(
        self,
        pergunta_original: str,
        objetivo: str,
        contexto_confirmado: str = "Nenhum dado confirmado disponível.",
        resumo_conversa: str = "Não fornecido.",
    ) -> ChemicalResult:
        payload = {
            "pergunta_original": pergunta_original,
            "objetivo": objetivo,
            "contexto_confirmado": contexto_confirmado,
            "resumo_conversa": resumo_conversa,
        }
        return await self._agent.ainvoke(payload)