from uuid import uuid4
import pytest
from app.agent.specialists.bau import bau_tools
from app.agent.specialists.quimico import quimico_tools
from app.agent.specialists.gps.gps_agent import GpsAgent


def test_bau_identity_is_bound_and_all_queries_filter_owner(monkeypatch):
    owner = str(uuid4())
    queries = []
    monkeypatch.setattr(bau_tools, "query", lambda sql, params: queries.append((sql, params)) or {"status": "ok", "dados": []})
    tools = bau_tools.create_bau_tools(owner)
    arguments = [{}, {"id_estante": 12}, {"nome_comodo": "banheiro"}, {}, {}]
    for item, args in zip(tools, arguments):
        assert "user_id" not in item.args
        item.invoke(args)
    assert len(queries) == 5
    assert all("id_usuario = %s" in sql and params[0] == owner for sql, params in queries)


def test_bau_rejects_invalid_identity():
    with pytest.raises(ValueError):
        bau_tools.create_bau_tools("invalid")


def test_match_without_incompatibility_rule_does_not_confirm_compatibility(monkeypatch):
    captured = []
    monkeypatch.setattr(quimico_tools, "query", lambda sql, params: captured.append((sql, params)) or {"status": "ok", "dados": [{"resultado": "compativel"}]})
    result = quimico_tools.verificar_compatibilidade_produtos.invoke({"id_produto_a": 1, "id_produto_b": 2})
    assert captured == [("SELECT * FROM fn_match_produtos(%s, %s)", (1, 2))]
    assert result["dados"][0]["resultado"] == "nao_avaliado"
    assert result["informacoes_suficientes"] is False
    assert "informações suficientes no app" in result["message"]


@pytest.mark.parametrize("rows", [[], [{"resultado": "nao_avaliado"}]])
def test_match_missing_information_is_explicit(monkeypatch, rows):
    monkeypatch.setattr(quimico_tools, "query", lambda *args: {"status": "ok", "dados": rows})
    result = quimico_tools.verificar_compatibilidade_produtos.invoke({"id_produto_a": 1, "id_produto_b": 2})
    assert result["informacoes_suficientes"] is False
    assert "informações suficientes no app" in result["message"]


def test_match_preserves_confirmed_incompatibility(monkeypatch):
    row = {"resultado": "incompativel", "severidade": "alta", "descricao_risco": "Risco confirmado"}
    monkeypatch.setattr(quimico_tools, "query", lambda *args: {"status": "ok", "dados": [row]})
    result = quimico_tools.verificar_compatibilidade_produtos.invoke({"id_produto_a": 1, "id_produto_b": 2})
    assert result["dados"] == [row]


def test_gps_uses_model_without_tools_or_location_context():
    from langchain_core.runnables import RunnableLambda
    calls = []
    class Model:
        def with_structured_output(self, schema):
            def respond(messages):
                calls.append(messages)
                return {"dominio": "gps", "intencao": "consultar",
                        "resposta": "Não jogue na pia. Consulte a funcionalidade Proximidade."}
            return RunnableLambda(respond)
    response = GpsAgent(model=Model()).invoke("Onde fica?", "Buscar", "Rua inventada 123")
    assert len(calls) == 1
    assert "Rua inventada" not in str(calls[0])
    assert "Proximidade" in response.resposta
    assert "Rua inventada" not in response.resposta
    assert response.esclarecer is None


def test_tool_agent_executes_queries_before_structured_answer():
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from langchain_core.tools import tool
    from app.agent.contracts import QuimicoResult
    from app.agent.specialists.tool_agent import ToolAgent
    executions = []

    @tool
    def consulta() -> dict:
        """Retorna dados confirmados de teste."""
        executions.append("consulta")
        return {"status": "ok", "dados": [{"nome": "Produto confirmado"}]}

    class Model:
        rounds = 0

        def bind_tools(self, tools):
            def respond(messages):
                self.rounds += 1
                return AIMessage(content="", tool_calls=[{"name": "consulta", "args": {}, "id": "1"}]) if self.rounds == 1 else AIMessage(content="")
            return RunnableLambda(respond)

        def with_structured_output(self, schema):
            def respond(messages):
                assert executions == ["consulta"]
                assert "Produto confirmado" in messages[-1].content
                return QuimicoResult(intencao="consultar", resposta="Produto confirmado")
            return RunnableLambda(respond)

    result = ToolAgent(Model(), [consulta], "Prompt", QuimicoResult).invoke({"pergunta_original": "Qual produto?"})
    assert result.resposta == "Produto confirmado"
