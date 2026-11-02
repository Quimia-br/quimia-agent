from functools import lru_cache
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

    def independent_structured_outputs(self, schema: Any) -> list[Any]:
        """Um leitor por modelo, sem um servir de reserva do outro: para conferir uma resposta com a de outro modelo."""
        models = [self._primary] + ([self._fallback] if self._fallback is not None else [])
        return [model.with_structured_output(schema, method="json_mode") for model in models]

    def bind_tools(self, tools: list) -> Any:
        primary = self._primary.bind_tools(tools)
        if self._fallback is None:
            return primary
        return primary.with_fallbacks([self._fallback.bind_tools(tools)])


def create_chat_model() -> ChatModelWithFallback:
    """Modelo de chat da Provider API com a chave compartilhada.

    O mesmo par de clientes serve todas as requisições enquanto a configuração não muda: recriá-los a cada
    pergunta refazia o TLS com o provedor em cada etapa.
    """
    config = carregar_config()
    if not config.commandcode_api_key:
        raise ModelConfigurationError("COMMANDCODE_API_KEY não está configurada.")
    return _modelo(
        config.commandcode_api_key,
        config.commandcode_base_url,
        config.commandcode_model,
        config.commandcode_model_fallback,
        config.commandcode_timeout_seconds,
        config.commandcode_max_retries,
        config.commandcode_reasoning_effort,
    )


@lru_cache(maxsize=8)
def _modelo(
    api_key, base_url, model, fallback, timeout, max_retries, reasoning_effort=None
) -> ChatModelWithFallback:
    def build(model_name: str):
        extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        return ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=0,
            timeout=timeout,
            max_retries=max_retries,
            **extra,
        )

    return ChatModelWithFallback(build(model), build(fallback))
