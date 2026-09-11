from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(
        ...,
        description="ID da sessão atual para manter histórico de conversas."
    )
    id: str = Field(
        ...,
        description="Identificador do usuário"
    )
    pergunta: str = Field(
        ...,
        min_length=1,
        description="A mensagem do usuário."
    )


class ChatResponse(BaseModel):
    resposta: str = Field(..., description="Resposta finalpara o usuario")
   