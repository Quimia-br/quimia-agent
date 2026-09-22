from contextlib import contextmanager
import psycopg2
from app.core.config import DATABASE_URL

@contextmanager
def get_conn():
    """Garante abertura e fechamento/rollback automático da conexão."""
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()