import json
from typing import Any

from pydantic import BaseModel, Field

from app.agent.base import StructuredAgent
from app.agent.llms import create_chat_model
from app.agent.prompts import RESUMO_SESSAO_PROMPT
from app.observability.callbacks import MetricsCallback
from app.observability.telemetry import current, span

MAX_SUMMARY_CHARS = 1200


class SessionSummary(BaseModel):
    resumo: str = Field(min_length=1, max_length=MAX_SUMMARY_CHARS)


class SessionSummarizer:
    """Resume os turnos de uma sessão encerrada."""

    def __init__(self, model: Any | None = None) -> None:
        self._agent = StructuredAgent(
            system_prompt=RESUMO_SESSAO_PROMPT,
            human_template="TURNOS_DA_CONVERSA:\n{turnos}",
            output_schema=SessionSummary,
            model=model or create_chat_model(),
        )

    async def ainvoke(self, turns: list[dict[str, str]]) -> SessionSummary:
        trace = current.get()
        config = {"callbacks": [MetricsCallback(trace)]} if trace else None
        with span("resumo_sessao", kind="stage"):
            return await self._agent.ainvoke(
                {"turnos": json.dumps(turns, ensure_ascii=False)}, config=config)
