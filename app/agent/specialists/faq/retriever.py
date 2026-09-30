"""Recuperação semântica dos trechos oficiais do FAQ armazenados no Qdrant."""

from collections.abc import Sequence
from typing import Any

from app.agent.contracts import Evidence
from app.core.config import AppConfig, carregar_config
from app.agent.specialists.faq.vectorstore import get_embeddings, get_qdrant_client


def _page_number(payload: dict[str, Any]) -> int | None:
    value = payload.get("page_number")
    if isinstance(value, int) and value >= 1:
        return value
    return None


def retrieve_faq_evidence(
    question: str,
    *,
    client: Any | None = None,
    embeddings: Any | None = None,
    config: AppConfig | None = None,
) -> list[Evidence]:
    """Busca no Qdrant os trechos do PDF mais próximos da pergunta."""
    normalized_question = question.strip()
    if not normalized_question:
        return []

    active_config = config or carregar_config()
    active_client = client or get_qdrant_client()
    active_embeddings = embeddings or get_embeddings()
    query_vector = active_embeddings.embed_query(normalized_question)

    response = active_client.query_points(
        collection_name=active_config.faq_collection,
        query=query_vector,
        limit=active_config.faq_top_k,
        score_threshold=active_config.faq_score_threshold,
        with_payload=True,
    )

    evidence: list[Evidence] = []
    points: Sequence[Any] = getattr(response, "points", ())
    for point in points:
        payload = point.payload or {}
        content = str(payload.get("page_content", "")).strip()
        if not content:
            continue
        evidence.append(
            Evidence(
                source_id=f"faq:{point.id}",
                title="Quimia - Instrução Normativa de Uso FAQ de Funcionalidades",
                content=content,
                uri=str(payload.get("source", "")) or None,
                page=_page_number(payload),
            )
        )
    return evidence