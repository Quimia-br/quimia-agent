"""Tools de consulta ao catálogo e às FDS ativas."""
from langchain_core.tools import tool
from app.agent.specialists.sql_tools import query, positive_id, limit_rows

SAFETY_NOTICE = (
    "O Quimia oferece apoio informativo e não substitui o rótulo, a FDS ou o fabricante. "
    "A ausência de regra de incompatibilidade não confirma compatibilidade. "
    "Sem confirmação técnica suficiente, não misture."
)
INSUFFICIENT_INFORMATION = (
    "Não há informações suficientes no app para confirmar se esses produtos podem "
    "ser misturados com segurança. Não misture e confirme as orientações do fabricante."
)


@tool
def buscar_produto(termo: str, limite: int = 20) -> dict:
    """Busca produtos por nome, marca ou código de barras. Não escolhe entre candidatos ambíguos."""
    termo = termo.strip()
    if not termo:
        return {"status": "error", "message": "Informe nome, marca ou código de barras."}
    return query("""SELECT p.id, p.nome, m.nome AS marca, p.descricao, p.tipo_produto,
        p.cod_barras FROM produto p JOIN marca m ON m.id = p.id_marca
        WHERE p.nome ILIKE %s OR m.nome ILIKE %s OR p.cod_barras = %s
        ORDER BY p.nome, p.id LIMIT %s""", (f"%{termo}%", f"%{termo}%", termo, limit_rows(limite)))


@tool
def consultar_composicao_produto(id_produto: int) -> dict:
    """Consulta compostos das FDS ativas, inclusive os não resolvidos."""
    return query("""WITH fds_ativas AS (
            SELECT id, versao, data_atualizacao, raw_json FROM fds
            WHERE id_produto = %s AND ativo = TRUE
        ), compostos AS (
            SELECT fc.*, ROW_NUMBER() OVER (PARTITION BY fc.id_fds ORDER BY fc.id) AS ordem
            FROM fds_composto fc JOIN fds_ativas f ON f.id = fc.id_fds
        )
        SELECT f.id AS id_fds, f.versao, f.data_atualizacao,
            fc.id_substancia,
            COALESCE(s.nome_canonico, pend.termo_bruto, bruto.item ->> 'nome',
                     'Composto não identificado') AS nome_composto,
            COALESCE(s.cas_numero, pend.cas_bruto, bruto.item ->> 'cas_numero') AS cas_numero,
            (fc.id_substancia IS NOT NULL) AS substancia_resolvida,
            fc.concentracao_min, fc.concentracao_max, fc.unidade_concentracao
        FROM fds_ativas f JOIN compostos fc ON fc.id_fds = f.id
        LEFT JOIN substancia s ON s.id = fc.id_substancia
        LEFT JOIN LATERAL (
            SELECT f.raw_json #> ARRAY['secoes', '03', 'compostos', (fc.ordem - 1)::text] AS item
        ) bruto ON TRUE
        LEFT JOIN LATERAL (
            SELECT sp.termo_bruto, sp.cas_bruto FROM sinonimo_pendente sp
            WHERE sp.id_fds = f.id AND sp.status = 'pendente'
              AND sp.termo_bruto = COALESCE(bruto.item ->> 'nome', '(sem nome)')
              AND sp.cas_bruto IS NOT DISTINCT FROM (bruto.item ->> 'cas_numero')
            ORDER BY sp.id DESC LIMIT 1
        ) pend ON fc.id_substancia IS NULL
        ORDER BY f.id, fc.id LIMIT 100""",
        (positive_id(id_produto),))


@tool
def verificar_compatibilidade_produtos(id_produto_a: int, id_produto_b: int) -> dict:
    """Executa fn_match_produtos; o modelo explica o resultado sem decidir compatibilidade."""
    a, b = positive_id(id_produto_a), positive_id(id_produto_b)
    if a == b:
        return {"status": "error", "message": "Selecione dois produtos diferentes."}
    result = query("SELECT * FROM fn_match_produtos(%s, %s)", (a, b))
    if result.get("status") == "ok":
        rows = result.get("dados", [])
        # A função do banco chama ausência de regra de 'compativel'. Isso não
        # fornece evidência positiva de segurança para o assistente.
        for row in rows:
            if row.get("resultado") in ("compativel", "nao_avaliado"):
                row["resultado"] = "nao_avaliado"
        if not rows or any(row.get("resultado") == "nao_avaliado" for row in rows):
            result["informacoes_suficientes"] = False
            result["message"] = INSUFFICIENT_INFORMATION
    result["aviso_de_seguranca"] = SAFETY_NOTICE
    return result


@tool
def consultar_incompatibilidades_produto(id_produto: int) -> dict:
    """Consulta incompatibilidades das FDS ativas; ausência não comprova segurança."""
    return query("""SELECT f.id AS id_fds, f.versao, fi.substancia_reagente,
        fi.descricao_risco, fi.severidade, s.nome_canonico, cq.nome AS classe_quimica
        FROM fds f JOIN fds_incompatibilidade fi ON fi.id_fds = f.id
        LEFT JOIN substancia s ON s.id = fi.id_substancia
        LEFT JOIN classe_quimica cq ON cq.id = fi.id_classe_quimica
        WHERE f.id_produto = %s AND f.ativo = TRUE
        ORDER BY f.id, fi.id LIMIT 100""",
        (positive_id(id_produto),))


@tool
def consultar_primeiros_socorros(id_produto: int, rota_exposicao: str | None = None) -> dict:
    """Consulta primeiros socorros cadastrados, sem diagnóstico ou substituição de emergência."""
    if rota_exposicao not in (None, "inalacao", "pele", "olhos", "ingestao"):
        return {"status": "error", "message": "Via de exposição inválida."}
    return query("""SELECT f.id AS id_fds, f.versao, ps.rota_exposicao, ps.descricao,
        ps.sintomas, ps.tratamento_especial, ps.atencao_medica_imediata
        FROM fds f JOIN fds_primeiro_socorro ps ON ps.id_fds = f.id
        WHERE f.id = (SELECT id FROM fds WHERE id_produto = %s AND ativo = TRUE
                      ORDER BY data_atualizacao DESC NULLS LAST, id DESC LIMIT 1)
        AND (%s::text IS NULL OR ps.rota_exposicao = %s) ORDER BY ps.id LIMIT 100""",
        (positive_id(id_produto), rota_exposicao, rota_exposicao))


QUIMICO_TOOLS = [buscar_produto, consultar_composicao_produto,
                 verificar_compatibilidade_produtos, consultar_incompatibilidades_produto,
                 consultar_primeiros_socorros]
