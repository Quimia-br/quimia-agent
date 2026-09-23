from typing import Literal

from pydantic import BaseModel, Field, model_validator

AgentName = Literal["quimico", "bau", "gps"]


class RoutePlan(BaseModel):
    id: str = Field(pattern=r"^r[1-3]$")
    agente: AgentName
    objetivo: str = Field(min_length=1)
    depende_de: list[str] = Field(default_factory=list)


class OrchestratorResult(BaseModel):
    status: Literal["roteado", "esclarecer", "fora_escopo"]
    pergunta_original: str
    rotas: list[RoutePlan] = Field(default_factory=list, max_length=3)
    esclarecer: str | None = None

    @model_validator(mode="after")
    def validate_status_contract(self):
        if self.status == "roteado" and not self.rotas:
            raise ValueError("O status 'roteado' exige pelo menos uma rota.")
        if self.status != "roteado" and self.rotas:
            raise ValueError("Somente o status 'roteado' pode conter rotas.")
        if self.status == "esclarecer" and not self.esclarecer:
            raise ValueError("O status 'esclarecer' exige uma pergunta.")
        if self.status != "esclarecer" and self.esclarecer is not None:
            raise ValueError("Somente o status 'esclarecer' pode pedir esclarecimento.")

        route_ids = [route.id for route in self.rotas]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("Os identificadores das rotas devem ser únicos.")

        seen: set[str] = set()
        for route in self.rotas:
            if any(dependency not in seen for dependency in route.depende_de):
                raise ValueError("Uma rota só pode depender de rotas anteriores.")
            seen.add(route.id)
        return self


class SpecialistResult(BaseModel):
    dominio: AgentName
    intencao: Literal["consultar", "resumo"]
    resposta: str = Field(min_length=1)
    esclarecer: str | None = None


class ChemicalResult(SpecialistResult):
    dominio: Literal["quimico"] = "quimico"


class VaultResult(SpecialistResult):
    dominio: Literal["bau"] = "bau"


class GpsResult(SpecialistResult):
    dominio: Literal["gps"] = "gps"


class SynthesisResult(BaseModel):
    resposta: str = Field(min_length=1)
    esclarecer: str | None = None


class Evidence(BaseModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    uri: str | None = None
    page: int | None = Field(default=None, ge=1)


class JudgeResult(BaseModel):
    veredito: Literal["aprovado", "revisar", "bloqueado"]
    confianca: float = Field(ge=0, le=1)
    justificativa: str = Field(min_length=1)
    alegacoes_nao_sustentadas: list[str] = Field(default_factory=list)
    riscos_seguranca: list[str] = Field(default_factory=list)
    correcoes_necessarias: list[str] = Field(default_factory=list)

    @property
    def aprovado(self) -> bool:
        return self.veredito == "aprovado"

    @model_validator(mode="after")
    def validate_verdict_contract(self):
        problems = self.alegacoes_nao_sustentadas + self.riscos_seguranca
        if self.veredito == "aprovado" and (problems or self.correcoes_necessarias):
            raise ValueError("Um veredito aprovado não pode conter problemas.")
        if self.veredito == "revisar" and not self.correcoes_necessarias:
            raise ValueError("O veredito 'revisar' exige correções necessárias.")
        if self.veredito == "bloqueado" and not self.riscos_seguranca:
            raise ValueError("O veredito 'bloqueado' exige ao menos um risco.")
        return self