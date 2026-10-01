from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1, max_length=128,
        description="ID da sessão atual para manter histórico de conversas."
    )
    user_id: UUID = Field(
        ...,
        description="Identificador do usuário"
    )
    pergunta: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="A mensagem do usuário."
    )

    @field_validator("pergunta", "session_id")
    @classmethod
    def reject_blank(cls, value):
        if not value.strip():
            raise ValueError("O campo não pode conter apenas espaços.")
        return value


class ChatResponse(BaseModel):
    resposta: str = Field(..., description="Resposta final para o usuário")
   
