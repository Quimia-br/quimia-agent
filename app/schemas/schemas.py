from typing import Literal
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
    agentes_acionados: list[str] = Field(
        ..., description="Agentes chamados neste turno, na ordem de execução; repetições indicam revisão."
    )
   


class CloseSessionRequest(BaseModel):
    session_id: str = Field(
        ...,
        min_length=1, max_length=128,
        description="ID da sessão a encerrar."
    )
    user_id: UUID = Field(
        ...,
        description="Identificador do usuário dono da sessão"
    )

    @field_validator("session_id")
    @classmethod
    def reject_blank(cls, value):
        if not value.strip():
            raise ValueError("O campo não pode conter apenas espaços.")
        return value


class CloseSessionResponse(BaseModel):
    session_id: str
    status: Literal["resumida", "ja_resumida", "sem_turnos"] = Field(
        ...,
        description="resumida: resumo novo salvo; ja_resumida: a sessão já tinha resumo; sem_turnos: nada a resumir."
    )


class CandidatoRotulo(BaseModel):
    nome: str = Field(..., description="Nome do produto lido (ou o do catálogo, quando a leitura bate com ele).")
    marca: str | None = Field(None, description="Marca; nulo quando não foi lida.")
    cod_barras: str | None = Field(None, description="Dígitos do código de barras; nulo quando não foi lido.")


class BuscaPorImagemResponse(BaseModel):
    candidatos: list[CandidatoRotulo] = Field(..., description="Do mais provável ao menos; vazio sem rótulo legível.")
