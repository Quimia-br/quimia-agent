from contextlib import contextmanager

from fastapi.testclient import TestClient

import app.main as main_module
import app.routes.health_routes as health_routes


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query):
        assert query == "SELECT 1"

    def fetchone(self):
        return (1,)


class FakeConnection:
    def cursor(self):
        return FakeCursor()


class FakeAdmin:
    def command(self, command):
        assert command == "ping"
        return {"ok": 1}


class FakeDatabase:
    class Client:
        admin = FakeAdmin()

    client = Client()


@contextmanager
def healthy_postgres():
    yield FakeConnection()


def configure_test_app(monkeypatch):
    monkeypatch.setattr(main_module, "validar_config", lambda: [])
    monkeypatch.setattr(main_module, "close_mongo", lambda: None)


def test_health_returns_dependencies_answer(monkeypatch):
    configure_test_app(monkeypatch)
    monkeypatch.setattr(health_routes, "get_conn", healthy_postgres)
    monkeypatch.setattr(health_routes, "get_db", lambda: FakeDatabase())

    with TestClient(main_module.app) as client:
        response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["services"] == {
        "postgres": "healthy",
        "mongodb": "healthy",
    }


def test_health_returns_error_details(monkeypatch):
    configure_test_app(monkeypatch)

    @contextmanager
    def failing_postgres():
        raise RuntimeError("password=secret")
        yield

    monkeypatch.setattr(health_routes, "get_conn", failing_postgres)
    monkeypatch.setattr(health_routes, "get_db", lambda: FakeDatabase())

    with TestClient(main_module.app) as client:
        response = client.get("/health/")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["postgres"] == "unhealthy"
    assert "secret" not in response.text