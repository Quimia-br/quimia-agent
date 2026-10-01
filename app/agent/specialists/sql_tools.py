"""Consultas parametrizadas, limitadas e sem escrita para especialistas."""
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg2.extras import RealDictCursor

from app.database.postgres import get_pg

logger = logging.getLogger(__name__)


def serialize(value):
    if isinstance(value, (date, datetime, UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value).__name__)


def query(sql, params=()):
    try:
        with get_pg() as conn:
            conn.set_session(readonly=True)
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute(sql, params)
                rows = [dict(row) for row in cursor.fetchall()]
        return {"status": "ok", "dados": json.loads(json.dumps(rows, default=serialize)),
                "encontrado": bool(rows)}
    except Exception:
        logger.exception("Falha na consulta de especialista")
        return {"status": "error", "message": "Não foi possível consultar os dados agora."}


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("O identificador deve ser um inteiro positivo.")
    return value


def limit_rows(value):
    return min(positive_id(value), 100)
