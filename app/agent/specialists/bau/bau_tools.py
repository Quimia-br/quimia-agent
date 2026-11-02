"""Tools pessoais: identidade vinculada pelo backend, nunca pelo modelo."""
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo
from langchain_core.tools import tool
from app.agent.specialists.sql_tools import query, positive_id, limit_rows

USER_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def create_bau_tools(user_id: str):
    owner = str(UUID(str(user_id)))

    @tool
    def listar_estantes_usuario(limite: int = 20) -> dict:
        """Lista as estantes do usuário autenticado."""
        return query("SELECT nome, criado_em FROM estante WHERE id_usuario = %s ORDER BY id LIMIT %s",
                     (owner, limit_rows(limite)))

    @tool
    def listar_produtos_estante(limite: int = 20) -> dict:
        """Lista produtos da estante pertencente ao usuário autenticado."""
        return query("""SELECT p.id, p.nome, m.nome AS marca, p.tipo_produto, ep.favorito
            FROM estante_produto ep JOIN estante e ON e.id = ep.id_estante
            JOIN produto p ON p.id = ep.id_produto JOIN marca m ON m.id = p.id_marca
            WHERE e.id_usuario = %s AND ep.id_usuario = %s
            ORDER BY p.nome, p.id LIMIT %s""", (owner, owner, limit_rows(limite)))

    @tool
    def listar_produtos_por_comodo(nome_comodo: str, limite: int = 20) -> dict:
        """Lista produtos pessoais associados a um cômodo do usuário pelo nome."""
        if not nome_comodo.strip():
            return {"status": "error", "message": "Informe o nome do cômodo."}
        return query("""SELECT DISTINCT p.id, p.nome, m.nome AS marca, c.nome AS comodo, ep.favorito
            FROM comodo c JOIN estante_produto ep ON ep.id_comodo = c.id
            JOIN produto p ON p.id = ep.id_produto
            JOIN marca m ON m.id = p.id_marca
            JOIN estante e ON e.id = ep.id_estante
            WHERE c.id_usuario = %s AND ep.id_usuario = %s AND e.id_usuario = %s
            AND c.nome ILIKE %s ORDER BY p.nome, p.id LIMIT %s""",
            (owner, owner, owner, f"%{nome_comodo.strip()}%", limit_rows(limite)))

    def history(table, columns, date_type, inicio, fim, limite):
        def boundary(value):
            if not value:
                return None
            parsed = datetime.fromisoformat(value)
            if date_type == "timestamp":
                return (parsed.astimezone(USER_TIMEZONE).replace(tzinfo=None)
                        if parsed.tzinfo else parsed)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=USER_TIMEZONE)

        start, end = boundary(inicio), boundary(fim)
        if start and end and start >= end:
            return {"status": "error", "message": "O início deve ser anterior ao fim."}
        # table/columns/date_type são constantes internas; valores externos são parametrizados.
        return query(f"""SELECT {columns} FROM {table} h WHERE h.id_usuario = %s
            AND (%s::{date_type} IS NULL OR h.data_consulta >= %s::{date_type})
            AND (%s::{date_type} IS NULL OR h.data_consulta < %s::{date_type})
            ORDER BY h.data_consulta DESC, h.id DESC LIMIT %s""",
            (owner, start, start, end, end, limit_rows(limite)))

    @tool
    def consultar_historico_misturas(inicio: str | None = None, fim: str | None = None, limite: int = 20) -> dict:
        """Consulta misturas pessoais. Datas ISO: início inclusivo, fim exclusivo."""
        return history("historico_match", "h.id, h.id_produto_a, h.id_produto_b, h.resultado, h.severidade, h.descricao_risco, h.data_consulta", "timestamptz", inicio, fim, limite)

    @tool
    def consultar_historico_recomendacoes(inicio: str | None = None, fim: str | None = None, limite: int = 20) -> dict:
        """Consulta recomendações pessoais. Datas ISO: início inclusivo, fim exclusivo."""
        return history("historico_recomendacao", "h.id, h.id_produto, h.resultado, h.dosagem_sugerida, h.data_consulta", "timestamp", inicio, fim, limite)

    return [listar_estantes_usuario, listar_produtos_estante, listar_produtos_por_comodo,
            consultar_historico_misturas, consultar_historico_recomendacoes]
