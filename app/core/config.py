import os

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

load_dotenv(find_dotenv())

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:8081"
OBRIGATORIAS = (
    "GROQ_API_KEY",
    "DATABASE_URL",
    "MONGODB_URI",
)


class AppConfig(BaseModel):
    gemini_api_key: str | None
    groq_api_key: str | None
    database_url: str | None
    mongodb_uri: str | None
    cors_origins: tuple[str, ...]
    groq_fast_model: str
    groq_specialist_model: str
    gemini_specialist_model: str
    groq_judge_model: str
    groq_timeout_seconds: float
    groq_max_retries: int


def _parse_cors_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def carregar_config() -> AppConfig:
    """Carrega e valida a configuração atual do ambiente."""
    return AppConfig(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        database_url=os.getenv("DATABASE_URL"),
        mongodb_uri=os.getenv("MONGODB_URI"),
        cors_origins=_parse_cors_origins(
            os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        ),
        groq_fast_model=os.getenv("GROQ_FAST_MODEL"),
        groq_specialist_model=os.getenv("GROQ_SPECIALIST_MODEL"),
        gemini_specialist_model=os.getenv("GEMINI_SPECIALIST_MODEL"),
        groq_timeout_seconds=os.getenv("GROQ_TIMEOUT_SECONDS", "30"),
        groq_max_retries=os.getenv("GROQ_MAX_RETRIES", "2"),

    )


CONFIG = carregar_config()

GEMINI_API_KEY = CONFIG.gemini_api_key
GROQ_API_KEY = CONFIG.groq_api_key
DATABASE_URL = CONFIG.database_url
MONGODB_URI = CONFIG.mongodb_uri
CORS_ORIGINS = CONFIG.cors_origins
GROQ_FAST_MODEL = CONFIG.groq_fast_model
GROQ_SPECIALIST_MODEL = CONFIG.groq_specialist_model
GROQ_JUDGE_MODEL = CONFIG.groq_judge_model


def validar_config() -> list[str]:
    """Devolve a lista de problemas de configuração (vazia = tudo certo)."""
    config = carregar_config()
    valores = {
        "GROQ_API_KEY": config.groq_api_key,
        "DATABASE_URL": config.database_url,
        "MONGODB_URI": config.mongodb_uri,
    }
    problemas = [
        f"Variável ausente no .env: {nome}"
        for nome, valor in valores.items()
        if not valor
    ]

    if not config.cors_origins:
        problemas.append("CORS_ORIGINS deve conter pelo menos uma origem.")
    elif "*" in config.cors_origins:
        problemas.append(
            'CORS_ORIGINS não pode conter "*" quando credenciais estão habilitadas.'
        )

    return problemas