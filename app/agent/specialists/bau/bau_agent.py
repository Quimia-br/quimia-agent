from app.agent.specialists.tool_agent import ToolAgent
from app.agent.specialists.bau.bau_tools import create_bau_tools
from typing import Any

from app.agent.contracts import BauResult
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import BAU_PROMPT_COMPLETO


class BauAgent:
    """Especialista no catálogo pessoal e histórico do usuário."""

    def __init__(self, model: Any | None = None, *, user_id: str | None = None) -> None:
        if user_id is None:
            raise ValueError("user_id autenticado é obrigatório para o agente Baú.")
        tools = create_bau_tools(user_id)
        selected_model = model or create_chat_model(ModelProfile.SPECIALIST)
        self._agent = ToolAgent(selected_model, tools, BAU_PROMPT_COMPLETO, BauResult)

    def invoke(
        self,
        pergunta_original: str,
        objetivo: str,
        contexto_confirmado: str = "Nenhum dado confirmado disponível.",
        resumo_conversa: str = "Não fornecido.",
    ) -> BauResult:
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
    ) -> BauResult:
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
