"""Recuperação obrigatória do FAQ oficial antes da resposta."""
from langchain_core.tools import tool
from app.agent.specialists.faq.retriever import retrieve_faq_evidence


@tool
def consultar_faq(pergunta: str) -> list[dict]:
    """Busca evidências do PDF oficial no Qdrant; lista vazia indica ausência de evidências."""
    return [item.model_dump() for item in retrieve_faq_evidence(pergunta)]
