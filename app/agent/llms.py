from typing import Any

from langchain_openai import ChatOpenAI

from app.core.config import carregar_config


class ModelConfigurationError(RuntimeError):
    """Erro de configuração que impede a criação do modelo de chat."""


class ChatModelWithFallback:
    """Aplica o mesmo contrato estruturado ao modelo primário e ao fallback."""

    def __init__(self, primary: Any, fallback: Any | None = None) -> None:
        self._primary = primary
        self._fallback = fallback

    def with_structured_output(self, schema: Any) -> Any:
        primary = self._primary.with_structured_output(schema, method="json_mode")
        if self._fallback is None:
            return primary

        fallback = self._fallback.with_structured_output(schema, method="json_mode")
        return primary.with_fallbacks([fallback])

    def bind_tools(self, tools: list) -> Any:
        primary = self._primary.bind_tools(tools)
        if self._fallback is None:
            return primary
        return primary.with_fallbacks([self._fallback.bind_tools(tools)])


def create_chat_model() -> ChatModelWithFallback:
    """Cria um modelo de chat da Provider API com a chave compartilhada."""
    config = carregar_config()
    if not config.commandcode_api_key:
        raise ModelConfigurationError("COMMANDCODE_API_KEY não está configurada.")

    def build(model_name: str):
        return ChatOpenAI(
            api_key=config.commandcode_api_key,
            base_url=config.commandcode_base_url,
            model=model_name,
            temperature=0,
            timeout=config.commandcode_timeout_seconds,
            max_retries=config.commandcode_max_retries,
        )

    return ChatModelWithFallback(
        build(config.commandcode_model), build(config.commandcode_model_fallback)
    )
