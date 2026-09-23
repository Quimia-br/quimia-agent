import json
from typing import Any

from app.agent.base import StructuredAgent
from app.agent.contracts import Evidence, JudgeResult, SpecialistResult, SynthesisResult
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import JUIZ_PROMPT_COMPLETO


class JudgeAgent:
    """Avalia sustentação factual, segurança e adequação da resposta final."""

    def __init__(self, model: Any | None = None) -> None:
        self._agent = StructuredAgent(
            system_prompt=JUIZ_PROMPT_COMPLETO,
            human_template=(
                "PERGUNTA_ORIGINAL:\n{pergunta_original}\n\n"
                "RESPOSTA_CANDIDATA:\n{resposta_candidata}\n\n"
                "RESPOSTAS_ESPECIALISTAS:\n{respostas_especialistas}\n\n"
                "EVIDENCIAS:\n{evidencias}"
            ),
            output_schema=JudgeResult,
            model=model or create_chat_model(ModelProfile.SPECIALIST),
        )

    @staticmethod
    def _payload(
        pergunta_original: str,
        resposta_candidata: SynthesisResult,
        respostas_especialistas: list[SpecialistResult],
        evidencias: list[Evidence],
    ) -> dict[str, str]:
        return {
            "pergunta_original": pergunta_original,
            "resposta_candidata": resposta_candidata.model_dump_json(),
            "respostas_especialistas": json.dumps(
                [response.model_dump() for response in respostas_especialistas],
                ensure_ascii=False,
            ),
            "evidencias": json.dumps(
                [evidence.model_dump() for evidence in evidencias],
                ensure_ascii=False,
            ),
        }

    def invoke(
        self,
        pergunta_original: str,
        resposta_candidata: SynthesisResult,
        respostas_especialistas: list[SpecialistResult],
        evidencias: list[Evidence] | None = None,
    ) -> JudgeResult:
        return self._agent.invoke(
            self._payload(
                pergunta_original,
                resposta_candidata,
                respostas_especialistas,
                evidencias or [],
            )
        )

    async def ainvoke(
        self,
        pergunta_original: str,
        resposta_candidata: SynthesisResult,
        respostas_especialistas: list[SpecialistResult],
        evidencias: list[Evidence] | None = None,
    ) -> JudgeResult:
        return await self._agent.ainvoke(
            self._payload(
                pergunta_original,
                resposta_candidata,
                respostas_especialistas,
                evidencias or [],
            )
        )