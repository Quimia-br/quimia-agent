import app.core.config as config


def test_validar_config_env(monkeypatch):
    for name in config.OBRIGATORIAS:
        monkeypatch.delenv(name, raising=False)

    problems = config.validar_config()

    assert len(problems) == len(config.OBRIGATORIAS)
    assert all(problem.startswith("Variável ausente no .env:") for problem in problems)


def test_validar_config_required_env(monkeypatch):
    for name in config.OBRIGATORIAS:
        monkeypatch.setenv(name, "test-value")

    assert config.validar_config() == []


def test_validar_config_cors(monkeypatch):
    for name in config.OBRIGATORIAS:
        monkeypatch.setenv(name, "test-value")
    monkeypatch.setenv("CORS_ORIGINS", "*")

    assert config.validar_config() == [
        'CORS_ORIGINS não pode conter "*" quando credenciais estão habilitadas.'
    ]