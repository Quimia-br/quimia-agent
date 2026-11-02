"""Contrato HTTP usado pelo quimia-api, sem rede ou serviços externos."""

from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.routes.chat_routes as chat_routes
from app.agent.workflow import ChatRunResult


def test_api_token_protects_chat_and_session_close(monkeypatch):
    monkeypatch.setenv("QUIMIA_AGENTE_TOKEN", "segredo-da-api")
    monkeypatch.setenv("AGENT_WARMUP", "0")
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    monkeypatch.setattr(chat_routes, "load_chat_context", lambda *_: "Não fornecido.")
    monkeypatch.setattr(chat_routes, "save_turn", lambda *_: None)
    monkeypatch.setattr(chat_routes, "has_summary", lambda *_: True)

    async def responder(pergunta, usuario, contexto, sessao):
        assert pergunta == "Posso misturar?"
        assert usuario == user_id
        assert sessao == "sessao-1"
        return ChatRunResult("Consulte o rótulo.", ["quimico"])

    monkeypatch.setattr(chat_routes, "run_chat", responder)
    user_id = str(uuid4())
    message = {"session_id": "sessao-1", "user_id": user_id, "pergunta": "Posso misturar?"}
    close = {"session_id": "sessao-1", "user_id": user_id}
    with TestClient(main.create_app()) as client:
        assert client.post("/chat", json=message).status_code == 401
        assert client.post("/chat", json=message,
                           headers={"Authorization": "Bearer incorreto"}).status_code == 401
        assert client.post("/chat/sessions/close", json=close).status_code == 401

        headers = {"Authorization": "Bearer segredo-da-api"}
        response = client.post("/chat", json=message, headers=headers)
        assert response.status_code == 200
        assert response.json()["resposta"] == "Consulte o rótulo."
        closed = client.post("/chat/sessions/close", json=close, headers=headers)
        assert closed.status_code == 200
        assert closed.json() == {"session_id": "sessao-1", "status": "ja_resumida"}


def test_api_token_protects_label_reading_but_not_health(monkeypatch):
    monkeypatch.setenv("QUIMIA_AGENTE_TOKEN", "segredo-da-api")
    monkeypatch.setenv("AGENT_WARMUP", "0")
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    with TestClient(main.create_app()) as client:
        assert client.post("/produtos/busca-por-imagem").status_code == 401
        assert client.post("/produtos/busca-por-imagem", headers={
            "Authorization": "Bearer segredo-da-api"}).status_code == 400
        assert client.get("/").status_code == 200


def test_local_chat_stays_available_without_service_token(monkeypatch):
    monkeypatch.delenv("QUIMIA_AGENTE_TOKEN", raising=False)
    monkeypatch.setenv("AGENT_WARMUP", "0")
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    with TestClient(main.create_app()) as client:
        assert client.post("/chat", json={}).status_code == 422
