from enum import StrEnum
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.core.config import carregar_config


class ModelProfile(StrEnum):
    FAST = "fast"
    SPECIALIST = "specialist"


class ModelConfigurationError(RuntimeError):
    """Erro de configuração que impede a criação do modelo de chat."""


class ChatModelWithFallback:
    """Aplica o mesmo contrato estruturado ao modelo primário e ao fallback."""

    def __init__(self, primary: Any, fallback: Any | None = None) -> None:
        self._primary = primary
        self._fallback = fallback

    def with_structured_output(self, schema: Any) -> Any:
        primary = self._primary.with_structured_output(schema)
        if self._fallback is None:
            return primary

        fallback = self._fallback.with_structured_output(schema)
        return primary.with_fallbacks([fallback])


def create_chat_model(profile: ModelProfile) -> ChatModelWithFallback:
    """Cria o modelo do perfil e habilita o fallback dos agentes especialistas."""
    config = carregar_config()
    if not config.groq_api_key:
        raise ModelConfigurationError("GROQ_API_KEY não está configurada.")

    models = {
        ModelProfile.FAST: config.groq_fast_model,
        ModelProfile.SPECIALIST: config.groq_specialist_model,
    }

    primary = ChatGroq(
        api_key=config.groq_api_key,
        model=models[profile],
        temperature=0,
        timeout=config.groq_timeout_seconds,
        max_retries=config.groq_max_retries,
    )

    fallback = None
    if profile is ModelProfile.SPECIALIST and config.gemini_api_key:
        fallback = ChatGoogleGenerativeAI(
            api_key=config.gemini_api_key,
            model=config.gemini_specialist_model,
            temperature=0,
            request_timeout=config.groq_timeout_seconds,
            retries=config.groq_max_retries,
        )

    return ChatModelWithFallback(primary, fallback)