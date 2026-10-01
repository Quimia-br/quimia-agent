"""Endpoint de chat para testes locais pelo Swagger."""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agent.workflow import run_chat
from app.database.mongo import get_mongo
from app.schemas.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def save_turn(user_id, session_id, pergunta, resposta):
    get_mongo().chat_turns.insert_one({"user_id": user_id, "session_id": session_id,
                                     "pergunta": pergunta, "resposta": resposta,
                                     "criado_em": datetime.now(timezone.utc)})


@router.post("/chat", response_model=ChatResponse)
async def conversar(request: ChatRequest) -> ChatResponse:
    """Uma mensagem do usuário, uma resposta do Kemi."""
    user_id = str(request.user_id)
    try:
        answer = await asyncio.wait_for(run_chat(request.pergunta, user_id), timeout=180)
        await asyncio.to_thread(save_turn, user_id, request.session_id, request.pergunta, answer)
        return ChatResponse(resposta=answer)
    except Exception:
        logger.exception("Falha ao processar chat")
        raise HTTPException(503, "Não foi possível concluir sua mensagem agora. Tente novamente em instantes.") from None
