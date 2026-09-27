import asyncio
import json
from collections.abc import Callable
from typing import Any

from app.agent.base import StructuredAgent
from app.agent.contracts import Evidence, FaqResult
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import FAQ_PROMPT_COMPLETO
from app.agent.specialists.faq.retriever import retrieve_faq_evidence

FaqRetriever = Callable[[str], list[Evidence]]
FAQ_NOT_FOUND = "Não encontrei essa informação no FAQ oficial do Quimia."


class FaqAgent:
    """Especialista em funcionalidades do Quimia com contexto recuperado do PDF."""

    def __init__(
        self,
        model: Any | None = None,
        retriever: FaqRetriever | None = None,
    ) -> None:
        self._retriever = retriever or retrieve_faq_evidence
        self._agent = StructuredAgent(
            system_prompt=FAQ_PROMPT_COMPLETO,
            human_template=(
                "PERGUNTA_ORIGINAL:\n{pergunta_original}\n\n"
                "OBJETIVO_DA_ROTA:\n{objetivo}\n\n"
                "TRECHOS_RECUPERADOS_DO_FAQ:\n{evidencias}"
            ),
            output_schema=FaqResult,
            model=model or create_chat_model(ModelProfile.FAST),
        )

    @staticmethod
    def _payload(
        pergunta_original: str,
        objetivo: str,
        evidencias: list[Evidence],
    ) -> dict[str, str]:
        return {
            "pergunta_original": pergunta_original,
            "objetivo": objetivo,
            "evidencias": json.dumps(
                [evidence.model_dump() for evidence in evidencias],
                ensure_ascii=False,
            ),
        }

    def invoke_with_evidence(
        self,
        pergunta_original: str,
        objetivo: str = "Responder a dúvida sobre o funcionamento do Quimia.",
    ) -> tuple[FaqResult, list[Evidence]]:
        evidencias = self._retriever(pergunta_original)
        if not evidencias:
            return FaqResult(intencao="consultar", resposta=FAQ_NOT_FOUND), []
        result = self._agent.invoke(
            self._payload(pergunta_original, objetivo, evidencias)
        )
        return result, evidencias

    def invoke(
        self,
        pergunta_original: str,
        objetivo: str = "Responder a dúvida sobre o funcionamento do Quimia.",
    ) -> FaqResult:
        result, _ = self.invoke_with_evidence(pergunta_original, objetivo)
        return result

    async def ainvoke_with_evidence(
        self,
        pergunta_original: str,
        objetivo: str = "Responder a dúvida sobre o funcionamento do Quimia.",
    ) -> tuple[FaqResult, list[Evidence]]:
        evidencias = await asyncio.to_thread(self._retriever, pergunta_original)
        if not evidencias:
            return FaqResult(intencao="consultar", resposta=FAQ_NOT_FOUND), []
        result = await self._agent.ainvoke(
            self._payload(pergunta_original, objetivo, evidencias)
        )
        return result, evidencias

    async def ainvoke(
        self,
        pergunta_original: str,
        objetivo: str = "Responder a dúvida sobre o funcionamento do Quimia.",
    ) -> FaqResult:
        result, _ = await self.ainvoke_with_evidence(pergunta_original, objetivo)
        return result