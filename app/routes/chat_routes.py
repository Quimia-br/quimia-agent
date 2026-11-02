"""Endpoint de chat para testes locais pelo Swagger."""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.workflow import run_chat
from app.memory.summarizer import SessionSummarizer
from app.memory.chat_history import load_chat_context
from app.memory.chat_summaries import has_summary, load_session_turns, save_summary
from app.database.mongo import get_mongo
from app.schemas.schemas import ChatRequest, ChatResponse, CloseSessionRequest, CloseSessionResponse
from app.core.config import carregar_config
from app.observability.telemetry import mark, span

logger = logging.getLogger(__name__)

SUMMARY_TIMEOUT_SECONDS = 60

router = APIRouter(tags=["chat"])


def save_turn(user_id, session_id, pergunta, resposta):
    get_mongo().chat_turns.insert_one({"user_id": user_id, "session_id": session_id,
                                     "pergunta": pergunta, "resposta": resposta,
                                     "criado_em": datetime.now(timezone.utc)})


def _salvar_turno(user_id, session_id, pergunta, resposta):
    """Grava depois de a resposta sair: o usuário não espera o MongoDB. Uma falha fica só no log."""
    try:
        with span("mongodb_save"):
            save_turn(user_id, session_id, pergunta, resposta)
    except Exception:
        logger.exception("Falha ao gravar o turno da conversa")


@router.post("/chat", response_model=ChatResponse)
async def conversar(request: ChatRequest, background: BackgroundTasks) -> ChatResponse:
    """Uma mensagem do usuário, uma resposta do Kemi.

    A hospedagem corta a conexão em cerca de 30 s e serve uma página HTML com status 200. O agente responde antes
    disso: passado o orçamento (`CHAT_BUDGET_SECONDS`, 25 s) devolve 504 em JSON, que a API traduz em `agente_timeout`.
    """
    user_id = str(request.user_id)
    try:
        # O orçamento cobre o histórico no MongoDB e o grafo juntos: é o que o usuário espera, e a hospedagem não
        # distingue as duas partes.
        async with asyncio.timeout(carregar_config().chat_budget_seconds):
            with span("mongodb_history"):
                context = await asyncio.to_thread(load_chat_context, user_id, request.session_id)
            result = await run_chat(request.pergunta, user_id, context, request.session_id)
        background.add_task(_salvar_turno, user_id, request.session_id, request.pergunta, result.resposta)
        return ChatResponse(resposta=result.resposta, agentes_acionados=result.agentes_acionados)
    except asyncio.TimeoutError:
        logger.warning("Chat acima do orçamento de tempo")
        mark(outcome="timeout")
        raise HTTPException(504, "A resposta demorou mais que o esperado. Tente novamente em instantes.") from None
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
