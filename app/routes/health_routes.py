# app/routes/health_routes.py

from datetime import datetime, timezone
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

# Importações ajustadas conforme os seus arquivos
from app.database.postgres import get_conn
from app.database.mongo import get_db

router = APIRouter(
    prefix="/health",
    tags=["Saúde da API"],
)

@router.get("/", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Endpoint de diagnósticos para validar o status da API e das conexões com o PostgreSQL e MongoDB.
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "postgres": "unknown",
            "mongodb": "unknown"
        }
    }
    
    is_healthy = True

    # Teste de conexão com o PostgreSQL 
    try:
        conn = get_conn()
        conn.close()
        health_status["services"]["postgres"] = "healthy"
    except Exception as e:
        health_status["services"]["postgres"] = f"unhealthy: {str(e)}"
        is_healthy = False

    # Teste de conexão com o MongoDB 
    try:
        db = get_db()
        db.client.admin.command("ping")
        health_status["services"]["mongodb"] = "healthy"
    except Exception as e:
        health_status["services"]["mongodb"] = f"unhealthy: {str(e)}"
        is_healthy = False

    if not is_healthy:
        health_status["status"] = "degraded"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=health_status
        )

    return health_status