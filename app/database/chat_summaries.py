"""Resumos de sessões encerradas, guardados no MongoDB."""

from datetime import datetime, timezone

from app.database.chat_history import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS
from app.database.mongo import get_mongo

MAX_SUMMARY_TURNS = 40


def has_summary(user_id: str, session_id: str) -> bool:
    return get_mongo().chat_summaries.find_one({"user_id": user_id, "session_id": session_id}, {"_id": 1}) is not None


def load_session_turns(user_id: str, session_id: str) -> list[dict[str, str]]:
    """Devolve os turnos mais recentes da sessão em ordem cronológica, com texto limitado."""
    cursor = (
        get_mongo().chat_turns.find(
            {"user_id": user_id, "session_id": session_id},
            {"_id": 0, "pergunta": 1, "resposta": 1},
        )
        .sort([("criado_em", -1), ("_id", -1)])
        .limit(MAX_SUMMARY_TURNS)
    )
    turns = [
        {"pergunta": turn["pergunta"][:MAX_QUESTION_CHARS], "resposta": turn["resposta"][:MAX_ANSWER_CHARS]}
        for turn in cursor
    ]
    turns.reverse()
    return turns


def save_summary(user_id: str, session_id: str, summary: str, turn_count: int) -> None:
    """Grava o resumo uma única vez por sessão: um segundo fechamento não sobrescreve o primeiro."""
    get_mongo().chat_summaries.update_one(
        {"user_id": user_id, "session_id": session_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "session_id": session_id,
                "resumo": summary,
                "turnos": turn_count,
                "criado_em": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
