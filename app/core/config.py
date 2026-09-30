import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel

load_dotenv(find_dotenv())

BASE_DIR = Path(__file__).resolve().parents[2]
FAQ_PDF_PATH = (
    BASE_DIR
    / "data"
    / "quimia_instrucao_normativa_faq_funcionalidades_v1.0.pdf"
)
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:8081"
OBRIGATORIAS = (
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "MONGODB_URI",
    "QDRANT_URL",
)


class AppConfig(BaseModel):
    gemini_api_key: str | None
    groq_api_key: str | None
    database_url: str | None
    mongodb_uri: str | None
    qdrant_url: str | None
    qdrant_api_key: str | None
    cors_origins: tuple[str, ...]
    groq_fast_model: str
    groq_specialist_model: str
    gemini_specialist_model: str
    groq_timeout_seconds: float
    groq_max_retries: int
    gemini_embedding_model: str
    embedding_dimension: int
    faq_collection: str
    faq_top_k: int
    faq_score_threshold: float


def _parse_cors_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def carregar_config() -> AppConfig:
    """Carrega e valida a configuração atual do ambiente."""
    return AppConfig(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        database_url=os.getenv("DATABASE_URL"),
        mongodb_uri=os.getenv("MONGODB_URI"),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        cors_origins=_parse_cors_origins(
            os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        ),
        groq_fast_model=os.getenv("GROQ_FAST_MODEL", "qwen/qwen3.6-27b"),
        groq_specialist_model=os.getenv(
            "GROQ_SPECIALIST_MODEL", "openai/gpt-oss-120b"
        ),
        gemini_specialist_model=os.getenv(
            "GEMINI_SPECIALIST_MODEL", "gemini-3.6-flash"
        ),
        groq_timeout_seconds=os.getenv("GROQ_TIMEOUT_SECONDS", "30"),
        groq_max_retries=os.getenv("GROQ_MAX_RETRIES", "2"),
        gemini_embedding_model=os.getenv(
            "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"
        ),
        embedding_dimension=os.getenv("EMBEDDING_DIMENSION", "768"),
        faq_collection=os.getenv("QDRANT_FAQ_COLLECTION", "quimia_faq_chunks"),
        faq_top_k=os.getenv("FAQ_TOP_K", "6"),
        faq_score_threshold=os.getenv("FAQ_SCORE_THRESHOLD", "0.45"),
    )


CONFIG = carregar_config()

GEMINI_API_KEY = CONFIG.gemini_api_key
GROQ_API_KEY = CONFIG.groq_api_key
DATABASE_URL = CONFIG.database_url
MONGODB_URI = CONFIG.mongodb_uri
QDRANT_URL = CONFIG.qdrant_url
QDRANT_API_KEY = CONFIG.qdrant_api_key
CORS_ORIGINS = CONFIG.cors_origins
GROQ_FAST_MODEL = CONFIG.groq_fast_model
GROQ_SPECIALIST_MODEL = CONFIG.groq_specialist_model

def validar_config() -> list[str]:
    """Devolve a lista de problemas de configuração (vazia = tudo certo)."""
    config = carregar_config()
    valores = {
        "GROQ_API_KEY": config.groq_api_key,
        "GEMINI_API_KEY": config.gemini_api_key,
        "DATABASE_URL": config.database_url,
        "MONGODB_URI": config.mongodb_uri,
        "QDRANT_URL": config.qdrant_url,
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

    if not FAQ_PDF_PATH.exists():
        problemas.append(f"PDF do FAQ não encontrado em: {FAQ_PDF_PATH}")

    return problemas