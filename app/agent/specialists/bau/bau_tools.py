"""Tools pessoais: identidade vinculada pelo backend, nunca pelo modelo."""
from datetime import datetime
from uuid import UUID
from langchain_core.tools import tool
from app.agent.specialists.sql_tools import query, positive_id, limit_rows


def create_bau_tools(user_id: str):
    owner = str(UUID(str(user_id)))

    @tool
    def listar_estantes_usuario(limite: int = 20) -> dict:
        """Lista as estantes do usuário autenticado."""
        return query("SELECT id, nome, criado_em FROM estante WHERE id_usuario = %s ORDER BY id LIMIT %s",
                     (owner, limit_rows(limite)))

    @tool
    def listar_produtos_estante(id_estante: int, limite: int = 20) -> dict:
        """Lista produtos de uma estante pertencente ao usuário autenticado."""
        return query("""SELECT p.id, p.nome, m.nome AS marca, p.tipo_produto
            FROM estante_produto ep JOIN estante e ON e.id = ep.id_estante
            JOIN produto p ON p.id = ep.id_produto JOIN marca m ON m.id = p.id_marca
            WHERE e.id_usuario = %s AND ep.id_usuario = %s AND e.id = %s
            ORDER BY p.nome, p.id LIMIT %s""", (owner, owner, positive_id(id_estante), limit_rows(limite)))

    @tool
    def listar_produtos_por_comodo(nome_comodo: str, limite: int = 20) -> dict:
        """Lista produtos pessoais associados a um cômodo do usuário pelo nome."""
        if not nome_comodo.strip():
            return {"status": "error", "message": "Informe o nome do cômodo."}
        return query("""SELECT DISTINCT p.id, p.nome, m.nome AS marca, c.nome AS comodo
            FROM comodo c JOIN produto p ON p.id_comodo = c.id
            JOIN marca m ON m.id = p.id_marca
            JOIN estante_produto ep ON ep.id_produto = p.id
            JOIN estante e ON e.id = ep.id_estante
            WHERE c.id_usuario = %s AND ep.id_usuario = %s AND e.id_usuario = %s
            AND c.nome ILIKE %s ORDER BY p.nome, p.id LIMIT %s""",
            (owner, owner, owner, nome_comodo.strip(), limit_rows(limite)))

    def history(table, columns, inicio, fim, limite):
        start = datetime.fromisoformat(inicio) if inicio else None
        end = datetime.fromisoformat(fim) if fim else None
        if start and end and start >= end:
            return {"status": "error", "message": "O início deve ser anterior ao fim."}
        # table/columns são constantes internas; valores externos são parametrizados.
        return query(f"""SELECT {columns} FROM {table} h WHERE h.id_usuario = %s
            AND (%s::timestamptz IS NULL OR h.data_consulta >= %s::timestamptz)
            AND (%s::timestamptz IS NULL OR h.data_consulta < %s::timestamptz)
            ORDER BY h.data_consulta DESC, h.id DESC LIMIT %s""",
            (owner, start, start, end, end, limit_rows(limite)))

    @tool
    def consultar_historico_misturas(inicio: str | None = None, fim: str | None = None, limite: int = 20) -> dict:
        """Consulta misturas pessoais. Datas ISO: início inclusivo, fim exclusivo."""
        return history("historico_match", "h.id, h.id_produto_a, h.id_produto_b, h.resultado, h.severidade, h.descricao_risco, h.data_consulta", inicio, fim, limite)

    @tool
    def consultar_historico_recomendacoes(inicio: str | None = None, fim: str | None = None, limite: int = 20) -> dict:
        """Consulta recomendações pessoais. Datas ISO: início inclusivo, fim exclusivo."""
        return history("historico_recomendacao", "h.id, h.id_produto, h.resultado, h.dosagem_sugerida, h.data_consulta", inicio, fim, limite)

    return [listar_estantes_usuario, listar_produtos_estante, listar_produtos_por_comodo,
            consultar_historico_misturas, consultar_historico_recomendacoes]
