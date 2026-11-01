import logging
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS, validar_config
from app.database.mongo import close_mongo
from app.routes.health_routes import router as health_router
from app.routes.chat_routes import router as chat_router
from app.routes.monitor_routes import router as monitor_router
from app.routes.produto_routes import router as produto_router
from app.observability.telemetry import observe_request
from app.observability import storage

logger = logging.getLogger(__name__)


def aquecer() -> None:
    """Abre as conexões e cria os clientes que o primeiro /chat usaria: a primeira pergunta depois de um deploy ou de
    um período parado levava uns 10 s só nisso. Falhas aqui não impedem a subida; a pergunta tenta de novo."""
    from app.agent.llms import create_chat_model
    from app.agent.specialists.faq.vectorstore import get_embeddings, get_qdrant_client
    from app.database.mongo import get_mongo
    from app.database.postgres import get_pg

    def postgres():
        with get_pg() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT 1")

    passos = {
        "modelos": create_chat_model,
        "qdrant": get_qdrant_client,
        "embeddings": get_embeddings,
        "mongodb": lambda: get_mongo().command("ping"),
        "postgres": postgres,
    }
    for nome, passo in passos.items():
        try:
            passo()
        except Exception:
            logger.warning("Aquecimento de %s falhou; a primeira pergunta abre essa conexão.", nome, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    erros = validar_config()
    if erros:
        mensagem = "\n".join(erros)
        raise RuntimeError(f"Erro ao iniciar a aplicação:\n{mensagem}")

    logger.info("Configurações validadas com sucesso.")
    if not storage.enabled():
        logger.warning("LangSmith desativado: as métricas não serão armazenadas.")

    if os.getenv("AGENT_WARMUP", "1") != "0":
        asyncio.get_running_loop().run_in_executor(None, aquecer)

    try:
        yield
    finally:
        try:
            await asyncio.to_thread(storage.flush)
        except Exception:
            logger.warning("Não foi possível concluir o envio dos traces ao LangSmith.")
        close_mongo()
        logger.info("Recursos da aplicação encerrados.")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Kemi API",
        description="Backend do assistente Kemi com múltiplos agentes e guardrails.",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health_router)
    application.include_router(chat_router)
    application.include_router(monitor_router)
    application.include_router(produto_router)
    application.middleware("http")(observe_request)

    @application.get("/")
    async def root():
        return {"message": "Kemi API está online."}

    return application


app = create_app()
