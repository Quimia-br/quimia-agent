import logging
from datetime import datetime, timezone

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.database.mongo import get_db
from app.database.postgres import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
    tags=["Saúde da API"],
)


@router.get("/", status_code=status.HTTP_200_OK)
def health_check():
    """Valida o acesso da API ao PostgreSQL e ao MongoDB."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "postgres": "unknown",
            "mongodb": "unknown",
        },
    }
    is_healthy = True

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise RuntimeError("Resposta inesperada do PostgreSQL.")
        health_status["services"]["postgres"] = "healthy"
    except Exception:
        logger.exception("Falha no health check do PostgreSQL.")
        health_status["services"]["postgres"] = "unhealthy"
        is_healthy = False

    try:
        db = get_db()
        db.client.admin.command("ping")
        health_status["services"]["mongodb"] = "healthy"
    except Exception:
        logger.exception("Falha no health check do MongoDB.")
        health_status["services"]["mongodb"] = "unhealthy"
        is_healthy = False

    if not is_healthy:
        health_status["status"] = "degraded"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status,
        )

    return health_status