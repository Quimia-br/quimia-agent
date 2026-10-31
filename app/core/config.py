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
    "COMMANDCODE_API_KEY",
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "MONGODB_URI",
    "QDRANT_URL",
)


class AppConfig(BaseModel):
    gemini_api_key: str | None
    commandcode_api_key: str | None
    commandcode_base_url: str
    database_url: str | None
    mongodb_uri: str | None
    qdrant_url: str | None
    qdrant_api_key: str | None
    cors_origins: tuple[str, ...]
    commandcode_model: str
    commandcode_model_fallback: str
    commandcode_timeout_seconds: float
    commandcode_max_retries: int
    gemini_embedding_model: str
    embedding_dimension: int
    faq_collection: str
    faq_top_k: int
    faq_score_threshold: float


def _parse_cors_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def normalize_commandcode_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if url == "https://api.commandcode.ai":
        return url + "/provider/v1"
    return url


def carregar_config() -> AppConfig:
    """Carrega e valida a configuração atual do ambiente."""
    return AppConfig(
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        commandcode_api_key=os.getenv("COMMANDCODE_API_KEY"),
        commandcode_base_url=normalize_commandcode_base_url(os.getenv(
            "COMMANDCODE_BASE_URL", "https://api.commandcode.ai/provider/v1"
        )),
        database_url=os.getenv("DATABASE_URL"),
        mongodb_uri=os.getenv("MONGODB_URI"),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        cors_origins=_parse_cors_origins(
            os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        ),
        commandcode_model=os.getenv("COMMANDCODE_MODEL", "xiaomi/mimo-v2.6-flash"),
        commandcode_model_fallback=os.getenv(
            "COMMANDCODE_MODEL_FALLBACK", "xiaomi/mimo-v2.6-pro"
        ),
        commandcode_timeout_seconds=os.getenv("COMMANDCODE_TIMEOUT_SECONDS", "30"),
        commandcode_max_retries=os.getenv("COMMANDCODE_MAX_RETRIES", "2"),
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
COMMANDCODE_API_KEY = CONFIG.commandcode_api_key
DATABASE_URL = CONFIG.database_url
MONGODB_URI = CONFIG.mongodb_uri
QDRANT_URL = CONFIG.qdrant_url
QDRANT_API_KEY = CONFIG.qdrant_api_key
CORS_ORIGINS = CONFIG.cors_origins
COMMANDCODE_MODEL = CONFIG.commandcode_model
COMMANDCODE_MODEL_FALLBACK = CONFIG.commandcode_model_fallback

def validar_config() -> list[str]:
    """Devolve a lista de problemas de configuração (vazia = tudo certo)."""
    config = carregar_config()
    valores = {
        "COMMANDCODE_API_KEY": config.commandcode_api_key,
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
