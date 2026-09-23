from typing import Any

from app.agent.base import StructuredAgent
from app.agent.contracts import OrchestratorResult
from app.agent.model_factory import ModelProfile, create_groq_chat_model
from app.agent.prompts import ORQUESTRADOR_PROMPT_COMPLETO


class OrchestratorAgent:
    """Classifica a intenção e cria o plano de roteamento dos especialistas."""

    def __init__(self, model: Any | None = None) -> None:
        self._agent = StructuredAgent(
            system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
            human_template=(
                "PERGUNTA_ORIGINAL:\n{pergunta_original}\n\n"
                "CONTEXTO_CONVERSA:\n{contexto_conversa}"
            ),
            output_schema=OrchestratorResult,
            model=model or create_groq_chat_model(ModelProfile.FAST),
        )

    def invoke(
        self, pergunta_original: str, contexto_conversa: str = "Não fornecido."
    ) -> OrchestratorResult:
        return self._agent.invoke(
            {
                "pergunta_original": pergunta_original,
                "contexto_conversa": contexto_conversa,
            }
        )

    async def ainvoke(
        self, pergunta_original: str, contexto_conversa: str = "Não fornecido."
    ) -> OrchestratorResult:
        return await self._agent.ainvoke(
            {
                "pergunta_original": pergunta_original,
                "contexto_conversa": contexto_conversa,
            }
        )