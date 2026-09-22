from pymongo import MongoClient
from app.core.config import MONGODB_URI


mongo: MongoClient | None = None


def get_db():
    """Obtém o banco somente quando uma operação realmente precisa dele."""
    global mongo
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI não está configurada. Consulte GET /health.")
    if mongo is None:
        mongo = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    return mongo["quimia"]


def close_mongo() -> None:
    """Fecha o cliente compartilhado do MongoDB durante o shutdown da API."""
    global mongo
    if mongo is not None:
        mongo.close()
        mongo = None