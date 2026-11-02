"""Busca seletiva de resumos de sessões anteriores do próprio usuário."""

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from app.database.mongo import get_mongo

MAX_CANDIDATES = 100
MAX_RESULTS = 3
MAX_SUMMARY_CHARS = 1200
STOPWORDS = frozenset({
    "a", "as", "ao", "com", "da", "das", "de", "do", "dos", "e", "em", "eu",
    "foi", "me", "na", "nas", "no", "nos", "o", "os", "para", "por", "que",
    "qual", "quais", "sobre", "um", "uma", "voce", "meu", "minha", "meus",
    "minhas", "contei", "disse", "falamos", "conversa", "conversas",
    "conversamos", "lembra", "lembrar", "ontem", "antes", "anterior",
    "anteriores", "ultima", "ultimo", "passada", "passado", "resumo",
})


def _terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return {word for word in re.findall(r"[a-z0-9]+", ascii_text)
            if len(word) > 2 and word not in STOPWORDS}


@tool
def buscar_resumos_conversas(user_id: str, session_id: str, pergunta: str) -> list[dict]:
    """Encontra até três resumos relevantes de outras sessões do mesmo usuário."""
    cursor = (get_mongo().chat_summaries.find(
        {"user_id": user_id, "session_id": {"$ne": session_id}},
        {"_id": 0, "session_id": 1, "resumo": 1, "criado_em": 1},
    ).sort([("criado_em", -1), ("_id", -1)]).limit(MAX_CANDIDATES))
    rows = list(cursor)
    if "ontem" in _terms_with_time(pergunta):
        yesterday = (datetime.now(ZoneInfo("America/Sao_Paulo")) - timedelta(days=1)).date()
        rows = [row for row in rows if row.get("criado_em") and
                row["criado_em"].astimezone(ZoneInfo("America/Sao_Paulo")).date() == yesterday]
    terms = _terms(pergunta)
    ranked = [(len(terms & _terms(row.get("resumo", ""))), index, row)
              for index, row in enumerate(rows) if row.get("resumo")]
    if terms:
        ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [{"session_id": row["session_id"],
             "resumo": row["resumo"][:MAX_SUMMARY_CHARS],
             "criado_em": row["criado_em"].isoformat() if row.get("criado_em") else None}
            for _, _, row in ranked[:MAX_RESULTS]]


def _terms_with_time(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return set(re.findall(r"[a-z0-9]+", "".join(
        char for char in normalized if not unicodedata.combining(char))))
