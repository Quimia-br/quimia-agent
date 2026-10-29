"""Endpoint de chat para testes locais pelo Swagger."""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.agent.workflow import run_chat
from app.agent.summarizer import SessionSummarizer
from app.database.chat_history import load_chat_context
from app.database.chat_summaries import has_summary, load_session_turns, save_summary
from app.database.mongo import get_mongo
from app.schemas.schemas import ChatRequest, ChatResponse, CloseSessionRequest, CloseSessionResponse

logger = logging.getLogger(__name__)

SUMMARY_TIMEOUT_SECONDS = 60

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
        context = await asyncio.to_thread(load_chat_context, user_id, request.session_id)
        result = await asyncio.wait_for(run_chat(request.pergunta, user_id, context), timeout=180)
        await asyncio.to_thread(save_turn, user_id, request.session_id, request.pergunta, result.resposta)
        return ChatResponse(resposta=result.resposta, agentes_acionados=result.agentes_acionados)
    except Exception:
        logger.exception("Falha ao processar chat")
        raise HTTPException(503, "Não foi possível concluir sua mensagem agora. Tente novamente em instantes.") from None


@router.post("/chat/sessions/close", response_model=CloseSessionResponse)
async def encerrar_sessao(request: CloseSessionRequest) -> CloseSessionResponse:
    """Resume a sessão encerrada e guarda o resumo no MongoDB. Repetir a chamada não gera outro resumo."""
    user_id = str(request.user_id)
    try:
        if await asyncio.to_thread(has_summary, user_id, request.session_id):
            return CloseSessionResponse(session_id=request.session_id, status="ja_resumida")
        turns = await asyncio.to_thread(load_session_turns, user_id, request.session_id)
        if not turns:
            return CloseSessionResponse(session_id=request.session_id, status="sem_turnos")
        summary = await asyncio.wait_for(SessionSummarizer().ainvoke(turns), timeout=SUMMARY_TIMEOUT_SECONDS)
        await asyncio.to_thread(save_summary, user_id, request.session_id, summary.resumo, len(turns))
        return CloseSessionResponse(session_id=request.session_id, status="resumida")
    except Exception:
        logger.exception("Falha ao encerrar a sessão")
        raise HTTPException(503, "Não foi possível encerrar a sessão agora. Tente novamente em instantes.") from None
