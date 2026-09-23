import pytest
from langchain_core.runnables import RunnableLambda

import app.agent.llms as llms


class FakeChatModel:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.instances.append(self)

    def with_structured_output(self, _schema):
        return RunnableLambda(lambda payload: payload)


@pytest.mark.parametrize(
    ("profile", "expected_model"),
    [
        (llms.ModelProfile.FAST, "fast-model"),
        (llms.ModelProfile.SPECIALIST, "specialist-model"),
    ],
)
def test_llms_selects_model_by_profile(
    monkeypatch, profile, expected_model
):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_FAST_MODEL", "fast-model")
    monkeypatch.setenv("GROQ_SPECIALIST_MODEL", "specialist-model")
    monkeypatch.setattr(llms, "ChatGroq", FakeChatModel)

    llms.create_chat_model(profile)

    assert FakeChatModel.instances[0].kwargs["model"] == expected_model
    assert FakeChatModel.instances[0].kwargs["temperature"] == 0


def test_specialist_profile_enables_gemini_fallback(monkeypatch):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_SPECIALIST_MODEL", "gemini-fallback")
    monkeypatch.setattr(llms, "ChatGroq", FakeChatModel)
    monkeypatch.setattr(llms, "ChatGoogleGenerativeAI", FakeChatModel)

    llms.create_chat_model(llms.ModelProfile.SPECIALIST)

    assert len(FakeChatModel.instances) == 2
    assert FakeChatModel.instances[1].kwargs["model"] == "gemini-fallback"


def test_fast_profile_does_not_create_gemini_fallback(monkeypatch):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(llms, "ChatGroq", FakeChatModel)
    monkeypatch.setattr(llms, "ChatGoogleGenerativeAI", FakeChatModel)

    llms.create_chat_model(llms.ModelProfile.FAST)

    assert len(FakeChatModel.instances) == 1


def test_structured_model_uses_fallback_after_primary_failure():
    class FailingModel:
        def with_structured_output(self, _schema):
            def fail(_payload):
                raise RuntimeError("primary unavailable")

            return RunnableLambda(fail)

    class WorkingModel:
        def with_structured_output(self, _schema):
            return RunnableLambda(lambda _payload: {"provider": "fallback"})

    model = llms.ChatModelWithFallback(FailingModel(), WorkingModel())

    result = model.with_structured_output(dict).invoke({"question": "test"})

    assert result == {"provider": "fallback"}


def test_llms_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(llms.ModelConfigurationError):
        llms.create_chat_model(llms.ModelProfile.FAST)