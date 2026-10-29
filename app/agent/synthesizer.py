"""Entrega a resposta aprovada pelo guardrail de saída sem gerar novos fatos."""

from app.agent.contracts import SynthesisResult


class SynthesizerAgent:
    """Última etapa do fluxo: preserva exatamente o texto revisado."""

    def invoke(self, resposta_revisada: SynthesisResult) -> SynthesisResult:
        return resposta_revisada

    async def ainvoke(self, resposta_revisada: SynthesisResult) -> SynthesisResult:
        return self.invoke(resposta_revisada)
