"""Tools de consulta ao catálogo e às FDS ativas."""
import re

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
    """Busca produtos por nome, marca ou código de barras; aceita também nome (marca)."""
    termo = termo.strip()
    if not termo:
        return {"status": "error", "message": "Informe nome, marca ou código de barras."}
    nome_e_marca = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", termo)
    if nome_e_marca:
        nome, marca = (parte.strip() for parte in nome_e_marca.groups())
        return query("""SELECT p.id, p.nome, m.nome AS marca, p.descricao, p.tipo_produto,
            p.cod_barras FROM produto p JOIN marca m ON m.id = p.id_marca
            WHERE p.nome ILIKE %s AND m.nome ILIKE %s
            ORDER BY p.nome, p.id LIMIT %s""",
            (f"%{nome}%", marca, limit_rows(limite)))
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


ACENTUADAS = "áàâãäéèêëíìîïóòôõöúùûüç"
SEM_ACENTO = ACENTUADAS + ACENTUADAS.upper(), "aaaaaeeeeiiiiooooouuuuc" * 2
PRODUTOS_POR_TERMO = 5


def _normalizar(termo: str) -> str:
    return " ".join(termo.translate(str.maketrans(*SEM_ACENTO)).lower().split())


def _substancias_do_termo(termo: str) -> dict:
    """Substâncias a que o termo se refere: pelo nome ou sinônimo, ou pela composição das FDS ativas dos produtos
    com esse nome. Assim 'amônia' (uma substância) e 'água sanitária' (um produto) entram na mesma consulta."""
    padrao = f"%{_normalizar(termo)}%"
    resultado = query(f"""SELECT DISTINCT s.id, s.nome_canonico FROM substancia s
        LEFT JOIN substancia_sinonimo sn ON sn.id_substancia = s.id
        WHERE lower(translate(s.nome_canonico, '{SEM_ACENTO[0]}', '{SEM_ACENTO[1]}')) LIKE %s
           OR sn.sinonimo_normalizado LIKE %s
        UNION
        SELECT s.id, s.nome_canonico FROM substancia s WHERE s.id IN (
            SELECT fc.id_substancia FROM produto p JOIN fds f ON f.id_produto = p.id AND f.ativo = TRUE
            JOIN fds_composto fc ON fc.id_fds = f.id
            WHERE fc.id_substancia IS NOT NULL
              AND p.id IN (SELECT p2.id FROM produto p2
                           WHERE lower(translate(p2.nome, '{SEM_ACENTO[0]}', '{SEM_ACENTO[1]}')) LIKE %s
                           ORDER BY p2.id LIMIT {PRODUTOS_POR_TERMO}))
        ORDER BY 1 LIMIT 30""", (padrao, padrao, padrao))
    return resultado


def _classes_das_substancias(ids: list[int]) -> dict[int, list[str]]:
    """Classe química de cada substância: sem ela a regra 'hipocloritos com ácidos' não se liga ao vinagre."""
    if not ids:
        return {}
    resultado = query("""SELECT sc.id_substancia, c.nome FROM substancia_classe_quimica sc
        JOIN classe_quimica c ON c.id = sc.id_classe_quimica WHERE sc.id_substancia = ANY(%s)
        ORDER BY sc.id_substancia, c.nome""", (ids,))
    classes: dict[int, list[str]] = {}
    for linha in resultado.get("dados", []) if resultado.get("status") == "ok" else []:
        classes.setdefault(linha["id_substancia"], []).append(linha["nome"])
    return classes


@tool
def consultar_regra_entre_substancias(termo_a: str, termo_b: str) -> dict:
    """Regras de incompatibilidade cadastradas entre duas coisas citadas pelo nome, mesmo sem produto no catálogo:
    cada termo pode ser uma substância (amônia, vinagre) ou um produto (água sanitária). Ausência de regra não
    comprova segurança."""
    termos = (termo_a.strip(), termo_b.strip())
    if not all(termos):
        return {"status": "error", "message": "Informe os dois itens."}
    achados = [_substancias_do_termo(t) for t in termos]
    if any(a.get("status") != "ok" for a in achados):
        return {"status": "error", "message": "Não foi possível consultar os dados agora."}
    ids = [[s["id"] for s in a["dados"]] for a in achados]
    classes = _classes_das_substancias(sorted({i for lado in ids for i in lado}))
    lados = [{"termo": t, "substancias": [{**s, "classes": classes.get(s["id"], [])} for s in a["dados"]]}
             for t, a in zip(termos, achados)]
    if not all(ids):
        return {"status": "ok", "encontrado": False, "itens": lados, "regras": [],
                "message": "Algum dos itens não foi reconhecido no catálogo de substâncias do app.",
                "aviso_de_seguranca": SAFETY_NOTICE}

    def lado(coluna_substancia, coluna_classe, posicao):
        return (f"(r.{coluna_substancia} = ANY(%({posicao})s) OR r.{coluna_classe} IN "
                f"(SELECT id_classe_quimica FROM substancia_classe_quimica WHERE id_substancia = ANY(%({posicao})s)))")

    regras = query(f"""SELECT r.id, r.severidade, r.descricao_risco, r.fonte,
          COALESCE(sa.nome_canonico, ca.nome) AS lado_a, COALESCE(sb.nome_canonico, cb.nome) AS lado_b
        FROM incompatibilidade_regra r
        LEFT JOIN substancia sa ON sa.id = r.id_substancia_a LEFT JOIN classe_quimica ca ON ca.id = r.id_classe_a
        LEFT JOIN substancia sb ON sb.id = r.id_substancia_b LEFT JOIN classe_quimica cb ON cb.id = r.id_classe_b
        WHERE r.ativo = TRUE AND (
          ({lado('id_substancia_a', 'id_classe_a', 'a')} AND {lado('id_substancia_b', 'id_classe_b', 'b')})
          OR ({lado('id_substancia_a', 'id_classe_a', 'b')} AND {lado('id_substancia_b', 'id_classe_b', 'a')}))
        ORDER BY r.id LIMIT 20""", {"a": ids[0], "b": ids[1]})
    if regras.get("status") != "ok":
        return {"status": "error", "message": "Não foi possível consultar os dados agora."}
    return {"status": "ok", "encontrado": bool(regras["dados"]), "itens": lados, "regras": regras["dados"],
            "aviso_de_seguranca": SAFETY_NOTICE}


# Orientação padrão e conservadora para qualquer produto de limpeza, até o produto ser identificado. Texto a ser
# validado pela área de segurança do Quimia; o que a FDS do produto disser sobre primeiros socorros prevalece.
EMERGENCIA_GERAL = (
    "Em caso de emergência, ligue para o SAMU (192) ou para o Disque-Intoxicação (0800 722 6001) e tenha a "
    "embalagem do produto em mãos."
)
EMERGENCIA_POR_VIA = {
    "olhos": "Lave o olho com água corrente limpa por pelo menos 15 minutos, mantendo as pálpebras abertas, "
             "sem esfregar. Retire as lentes de contato se for fácil. Procure atendimento médico.",
    "pele": "Retire a roupa e os acessórios contaminados e lave a pele com bastante água corrente por pelo menos "
            "15 minutos. Procure atendimento médico se houver dor, vermelhidão persistente ou bolhas.",
    "inalacao": "Vá para um local arejado, ao ar livre. Se houver tosse, falta de ar ou mal-estar, procure "
                "atendimento médico.",
    "ingestao": "Não provoque vômito. Enxágue a boca com água, sem engolir, e procure atendimento médico "
                "imediatamente.",
}


@tool
def orientacao_geral_de_emergencia(rota_exposicao: str | None = None) -> dict:
    """Primeiros socorros genéricos para contato com produto de limpeza, para quando o produto não foi identificado.
    Não substitui a FDS do produto nem o atendimento médico."""
    if rota_exposicao not in (None, *EMERGENCIA_POR_VIA):
        return {"status": "error", "message": "Via de exposição inválida."}
    vias = {rota_exposicao: EMERGENCIA_POR_VIA[rota_exposicao]} if rota_exposicao else EMERGENCIA_POR_VIA
    return {"status": "ok", "encontrado": True, "orientacao_geral": vias, "emergencia": EMERGENCIA_GERAL,
            "aviso": "Orientação geral, não específica do produto. As instruções da FDS e do rótulo prevalecem."}


QUIMICO_TOOLS = [buscar_produto, consultar_composicao_produto,
                 verificar_compatibilidade_produtos, consultar_incompatibilidades_produto,
                 consultar_primeiros_socorros, orientacao_geral_de_emergencia,
                 consultar_regra_entre_substancias]
