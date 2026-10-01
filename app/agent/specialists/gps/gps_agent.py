from app.agent.contracts import GpsResult
from app.agent.base import StructuredAgent
from app.agent.llms import ModelProfile, create_chat_model
from app.agent.prompts import GPS_PROMPT_COMPLETO

GPS_RESPONSE = (
    "Não descarte o produto no chão, na pia, no vaso sanitário ou no lixo comum "
    "sem uma orientação confirmada. Consulte a funcionalidade Proximidade do Quimia "
    "para encontrar opções adequadas na sua região. Confirme a aceitação do resíduo "
    "com o ponto responsável antes de se deslocar."
)


class GpsAgent:
    """Agente de orientação genérica de descarte, com LLM e sem tools."""
    def __init__(self, model=None):
        self._agent = StructuredAgent(
            system_prompt=GPS_PROMPT_COMPLETO,
            human_template=("PERGUNTA_ORIGINAL:\n{pergunta_original}\n\n"
                            "OBJETIVO_DA_ROTA:\n{objetivo}\n\n"
                            "RESUMO_DA_CONVERSA:\n{resumo_conversa}"),
            output_schema=GpsResult,
            model=model if model is not None else create_chat_model(ModelProfile.FAST),
        )

    def invoke(self, pergunta_original, objetivo, contexto_confirmado=None, resumo_conversa=None):
        return self._agent.invoke({"pergunta_original": pergunta_original, "objetivo": objetivo,
                                   "resumo_conversa": resumo_conversa or "Não fornecido."})

    async def ainvoke(self, pergunta_original, objetivo, contexto_confirmado=None, resumo_conversa=None):
        return await self._agent.ainvoke({"pergunta_original": pergunta_original, "objetivo": objetivo,
                                         "resumo_conversa": resumo_conversa or "Não fornecido."})
