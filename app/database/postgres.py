"""Conexões com o PostgreSQL, reaproveitadas entre as consultas.

Abrir uma conexão com TLS para cada consulta custava de 0,5 a 1 s por ferramenta chamada. O pool mantém poucas
conexões abertas; uma conexão que o servidor já fechou (ocioso há muito tempo) é descartada na devolução.
"""
import threading
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import PoolError, ThreadedConnectionPool

from app.core.config import DATABASE_URL

POOL_MINIMO = 1
POOL_MAXIMO = 6
ESPERA_POR_CONEXAO_SEGUNDOS = 10.0

_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _obter_pool() -> ThreadedConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(POOL_MINIMO, POOL_MAXIMO, DATABASE_URL, connect_timeout=5)
        return _pool


def fechar_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


def _pegar(pool: ThreadedConnectionPool):
    """O pool recusa na hora quando está esgotado; com várias conversas ao mesmo tempo, espera um pouco por uma vaga."""
    limite = time.monotonic() + ESPERA_POR_CONEXAO_SEGUNDOS
    while True:
        try:
            return pool.getconn()
        except PoolError:
            if time.monotonic() >= limite:
                raise
            time.sleep(0.05)


@contextmanager
def get_pg():
    """Entrega uma conexão do pool; desfaz a transação ao fim e descarta a conexão que quebrou."""
    pool = _obter_pool()
    conn = _pegar(pool)
    quebrada = False
    try:
        yield conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        quebrada = True
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        if not quebrada and not conn.closed:
            try:
                conn.rollback()  # a conexão volta ao pool sem transação aberta
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                quebrada = True
        pool.putconn(conn, close=quebrada or bool(conn.closed))
