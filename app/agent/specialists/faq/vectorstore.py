"""Clientes de embeddings e Qdrant compartilhados pelo RAG do FAQ."""

from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient, models

from app.core.config import AppConfig, carregar_config


class FaqConfigurationError(RuntimeError):
    """Configuração ausente ou incompatível com o índice vetorial do FAQ."""


def _require_faq_config(config: AppConfig) -> None:
    if not config.gemini_api_key:
        raise FaqConfigurationError("GEMINI_API_KEY não está configurada.")
    if not config.qdrant_url:
        raise FaqConfigurationError("QDRANT_URL não está configurada.")


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    config = carregar_config()
    _require_faq_config(config)
    return QdrantClient(
        url=config.qdrant_url,
        api_key=config.qdrant_api_key or None,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    config = carregar_config()
    _require_faq_config(config)
    return GoogleGenerativeAIEmbeddings(
        model=config.gemini_embedding_model,
        api_key=config.gemini_api_key,
        output_dimensionality=config.embedding_dimension,
    )


def ensure_faq_collection(
    client: QdrantClient | None = None,
    config: AppConfig | None = None,
) -> None:
    """Cria a collection dedicada ao FAQ quando ela ainda não existe."""
    active_config = config or carregar_config()
    active_client = client or get_qdrant_client()
    if active_client.collection_exists(active_config.faq_collection):
        return

    active_client.create_collection(
        collection_name=active_config.faq_collection,
        vectors_config=models.VectorParams(
            size=active_config.embedding_dimension,
            distance=models.Distance.COSINE,
        ),
    )