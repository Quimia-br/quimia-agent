import asyncio
from typing import Any

from app.agent.contracts import Evidence, JudgeResult, SpecialistResult, SynthesisResult
from app.agent.jev import JevClient, build_state, to_judge_result


class JudgeAgent:
    """Avalia sustentação factual e segurança usando decisões do Jev."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else JevClient()

    def invoke(
        self,
        pergunta_original: str,
        resposta_candidata: SynthesisResult,
        respostas_especialistas: list[SpecialistResult],
        evidencias: list[Evidence] | None = None,
    ) -> JudgeResult:
        state = build_state(pergunta_original, resposta_candidata,
                            respostas_especialistas, evidencias or [])
        return to_judge_result(self._client.decide(state))

    async def ainvoke(
        self,
        pergunta_original: str,
        resposta_candidata: SynthesisResult,
        respostas_especialistas: list[SpecialistResult],
        evidencias: list[Evidence] | None = None,
    ) -> JudgeResult:
        return await asyncio.to_thread(self.invoke, pergunta_original,
                                       resposta_candidata, respostas_especialistas, evidencias)
