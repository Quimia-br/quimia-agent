from app.agent.specialists.tool_agent import ToolAgent
from app.agent.specialists.quimico.quimico_tools import QUIMICO_TOOLS
from typing import Any

from app.agent.contracts import QuimicoResult
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import QUIMICO_PROMPT_COMPLETO


class ChemicalAgent:
    """Especialista em produtos químicos, compatibilidade e segurança."""

    def __init__(self, model: Any | None = None) -> None:
        tools = QUIMICO_TOOLS
        selected_model = model or create_chat_model(ModelProfile.SPECIALIST)
        self._agent = ToolAgent(selected_model, tools, QUIMICO_PROMPT_COMPLETO, QuimicoResult)

    def invoke(
        self,
        pergunta_original: str,
        objetivo: str,
        contexto_confirmado: str = "Nenhum dado confirmado disponível.",
        resumo_conversa: str = "Não fornecido.",
    ) -> QuimicoResult:
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
    ) -> QuimicoResult:
        payload = {
            "pergunta_original": pergunta_original,
            "objetivo": objetivo,
            "contexto_confirmado": contexto_confirmado,
            "resumo_conversa": resumo_conversa,
        }
        return await self._agent.ainvoke(payload)
    async def ainvoke_with_evidence(self, pergunta_original, objetivo,
                                    contexto_confirmado="Nenhum dado confirmado disponível.",
                                    resumo_conversa="Não fornecido."):
        return await self._agent.ainvoke_with_evidence({
            "pergunta_original": pergunta_original,
            "objetivo": objetivo,
            "contexto_confirmado": contexto_confirmado,
            "resumo_conversa": resumo_conversa,
        })
