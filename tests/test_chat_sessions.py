from uuid import uuid4

from fastapi.testclient import TestClient

import app.database.chat_summaries as summaries
import app.main as main
import app.routes.chat_routes as routes
from app.agent.summarizer import SessionSummary

TURNS = [{"pergunta": "Posso misturar?", "resposta": "Não misture água sanitária com ácidos."}]


def client_for(monkeypatch):
    monkeypatch.setattr(main, "validar_config", lambda: [])
    monkeypatch.setattr(main, "close_mongo", lambda: None)
    return TestClient(main.create_app())


def payload():
    return {"user_id": str(uuid4()), "session_id": "session-1"}


def test_close_summarizes_and_saves_once(monkeypatch):
    saved = []
    seen = {}

    class Summarizer:
        async def ainvoke(self, turns):
            seen["turns"] = turns
            return SessionSummary(resumo="Usuário perguntou sobre misturas.")

    body = payload()
    monkeypatch.setattr(routes, "has_summary", lambda *args: False)
    monkeypatch.setattr(routes, "load_session_turns", lambda *args: TURNS)
    monkeypatch.setattr(routes, "SessionSummarizer", Summarizer)
    monkeypatch.setattr(routes, "save_summary", lambda *args: saved.append(args))
    with client_for(monkeypatch) as client:
        response = client.post("/chat/sessions/close", json=body)
    assert response.status_code == 200
    assert response.json() == {"session_id": "session-1", "status": "resumida"}
    assert seen["turns"] == TURNS
    assert saved == [(body["user_id"], "session-1", "Usuário perguntou sobre misturas.", 1)]


def test_close_is_idempotent_without_calling_the_model(monkeypatch):
    def forbidden(*args):
        raise AssertionError("não deve resumir de novo")

    monkeypatch.setattr(routes, "has_summary", lambda *args: True)
    monkeypatch.setattr(routes, "load_session_turns", forbidden)
    monkeypatch.setattr(routes, "SessionSummarizer", forbidden)
    with client_for(monkeypatch) as client:
        response = client.post("/chat/sessions/close", json=payload())
    assert response.status_code == 200
    assert response.json()["status"] == "ja_resumida"


def test_close_without_turns_saves_nothing(monkeypatch):
    def forbidden(*args):
        raise AssertionError("não deve salvar")

    monkeypatch.setattr(routes, "has_summary", lambda *args: False)
    monkeypatch.setattr(routes, "load_session_turns", lambda *args: [])
    monkeypatch.setattr(routes, "save_summary", forbidden)
    with client_for(monkeypatch) as client:
        response = client.post("/chat/sessions/close", json=payload())
    assert response.json() == {"session_id": "session-1", "status": "sem_turnos"}


def test_close_failure_does_not_expose_internals(monkeypatch):
    class Summarizer:
        async def ainvoke(self, turns):
            raise RuntimeError("password=secret")

    monkeypatch.setattr(routes, "has_summary", lambda *args: False)
    monkeypatch.setattr(routes, "load_session_turns", lambda *args: TURNS)
    monkeypatch.setattr(routes, "SessionSummarizer", Summarizer)
    with client_for(monkeypatch) as client:
        response = client.post("/chat/sessions/close", json=payload())
    assert response.status_code == 503
    assert "password" not in response.text


def test_close_validates_the_request(monkeypatch):
    with client_for(monkeypatch) as client:
        assert client.post("/chat/sessions/close", json={**payload(), "session_id": " "}).status_code == 422
        assert client.post("/chat/sessions/close", json={"session_id": "s", "user_id": "x"}).status_code == 422


def test_save_summary_never_overwrites_an_existing_one(monkeypatch):
    calls = []

    class Collection:
        def update_one(self, query, update, upsert):
            calls.append((query, update, upsert))

    class Database:
        chat_summaries = Collection()

    monkeypatch.setattr(summaries, "get_mongo", lambda: Database())
    summaries.save_summary("user-1", "session-1", "Resumo", 3)
    query, update, upsert = calls[0]
    assert query == {"user_id": "user-1", "session_id": "session-1"}
    assert set(update) == {"$setOnInsert"}
    assert update["$setOnInsert"]["resumo"] == "Resumo"
    assert update["$setOnInsert"]["turnos"] == 3
    assert upsert is True


def test_session_turns_are_chronological_limited_and_truncated(monkeypatch):
    class Cursor:
        rows = [
            {"pergunta": "p2", "resposta": "r" * (summaries.MAX_ANSWER_CHARS + 50)},
            {"pergunta": "p1", "resposta": "r1"},
        ]

        def sort(self, spec):
            assert spec == [("criado_em", -1), ("_id", -1)]
            return self

        def limit(self, count):
            assert count == summaries.MAX_SUMMARY_TURNS
            return self

        def __iter__(self):
            return iter(self.rows)

    class Collection:
        def find(self, query, projection):
            assert query == {"user_id": "user-1", "session_id": "session-1"}
            return Cursor()

    class Database:
        chat_turns = Collection()

    monkeypatch.setattr(summaries, "get_mongo", lambda: Database())
    turns = summaries.load_session_turns("user-1", "session-1")
    assert [turn["pergunta"] for turn in turns] == ["p1", "p2"]
    assert len(turns[1]["resposta"]) == summaries.MAX_ANSWER_CHARS
