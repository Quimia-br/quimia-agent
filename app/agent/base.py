from collections.abc import Mapping
import json
from typing import Any, Generic, TypeVar

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredAgent(Generic[SchemaT]):
    """Base LangChain para agentes com contrato de saída Pydantic."""

    def __init__(
        self,
        *,
        system_prompt: str,
        human_template: str,
        output_schema: type[SchemaT],
        model: Any,
    ) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=(
                    f"{system_prompt}\n\n"
                    "Responda somente com um objeto JSON válido que siga este esquema: "
                    f"{json.dumps(output_schema.model_json_schema(), ensure_ascii=False)}"
                )),
                ("human", human_template),
            ]
        )
        structured_model = model.with_structured_output(output_schema)
        self._chain = prompt | structured_model
        self._output_schema = output_schema

    def invoke(self, payload: Mapping[str, Any]) -> SchemaT:
        return self._validate(self._chain.invoke(dict(payload)))

    async def ainvoke(self, payload: Mapping[str, Any], config=None) -> SchemaT:
        return self._validate(await self._chain.ainvoke(dict(payload), config=config))

    def _validate(self, value: Any) -> SchemaT:
        if isinstance(value, self._output_schema):
            return value
        return self._output_schema.model_validate(value)
