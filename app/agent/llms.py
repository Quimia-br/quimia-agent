from enum import StrEnum
from typing import Any

from langchain_openai import ChatOpenAI

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
        primary = self._primary.with_structured_output(schema, method="function_calling")
        if self._fallback is None:
            return primary

        fallback = self._fallback.with_structured_output(schema, method="function_calling")
        return primary.with_fallbacks([fallback])

    def bind_tools(self, tools: list) -> Any:
        primary = self._primary.bind_tools(tools)
        if self._fallback is None:
            return primary
        return primary.with_fallbacks([self._fallback.bind_tools(tools)])


def create_chat_model(profile: ModelProfile) -> ChatModelWithFallback:
    """Cria um modelo de chat da Provider API com a chave compartilhada."""
    config = carregar_config()
    if not config.commandcode_api_key:
        raise ModelConfigurationError("COMMANDCODE_API_KEY não está configurada.")

    models = {
        ModelProfile.FAST: config.commandcode_fast_model,
        ModelProfile.SPECIALIST: config.commandcode_specialist_model,
    }

    primary = ChatOpenAI(
        api_key=config.commandcode_api_key,
        base_url=config.commandcode_base_url,
        model=models[profile],
        temperature=0,
        timeout=config.commandcode_timeout_seconds,
        max_retries=config.commandcode_max_retries,
    )
    return ChatModelWithFallback(primary)
