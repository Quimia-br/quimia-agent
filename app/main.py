import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS, validar_config
from app.database.mongo import close_mongo
from app.routes.health_routes import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    erros = validar_config()
    if erros:
        mensagem = "\n".join(erros)
        raise RuntimeError(f"Erro ao iniciar a aplicação:\n{mensagem}")

    logger.info("Configurações validadas com sucesso.")

    try:
        yield
    finally:
        close_mongo()
        logger.info("Recursos da aplicação encerrados.")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Quimia Agent API",
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

    @application.get("/")
    async def root():
        return {"message": "Quimia Agent API está online."}

    return application


app = create_app()