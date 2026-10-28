import pytest
from langchain_core.runnables import RunnableLambda

import app.agent.llms as llms


class FakeChatModel:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.instances.append(self)

    def with_structured_output(self, _schema, method="function_calling"):
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
    monkeypatch.setenv("COMMANDCODE_API_KEY", "test-key")
    monkeypatch.setenv("COMMANDCODE_FAST_MODEL", "fast-model")
    monkeypatch.setenv("COMMANDCODE_SPECIALIST_MODEL", "specialist-model")
    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatModel)

    llms.create_chat_model(profile)

    assert FakeChatModel.instances[0].kwargs["model"] == expected_model
    assert FakeChatModel.instances[0].kwargs["temperature"] == 0
    assert FakeChatModel.instances[0].kwargs["api_key"] == "test-key"
    assert FakeChatModel.instances[0].kwargs["base_url"] == "https://api.commandcode.ai/provider/v1"


def test_specialist_profile_uses_only_commandcode(monkeypatch):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("COMMANDCODE_API_KEY", "commandcode-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatModel)

    llms.create_chat_model(llms.ModelProfile.SPECIALIST)

    assert len(FakeChatModel.instances) == 1
    assert FakeChatModel.instances[0].kwargs["api_key"] == "commandcode-key"


def test_fast_profile_does_not_create_gemini_fallback(monkeypatch):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("COMMANDCODE_API_KEY", "commandcode-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatModel)

    llms.create_chat_model(llms.ModelProfile.FAST)

    assert len(FakeChatModel.instances) == 1


def test_structured_model_uses_fallback_after_primary_failure():
    class FailingModel:
        def with_structured_output(self, _schema, method="function_calling"):
            def fail(_payload):
                raise RuntimeError("primary unavailable")

            return RunnableLambda(fail)

    class WorkingModel:
        def with_structured_output(self, _schema, method="function_calling"):
            return RunnableLambda(lambda _payload: {"provider": "fallback"})

    model = llms.ChatModelWithFallback(FailingModel(), WorkingModel())

    result = model.with_structured_output(dict).invoke({"question": "test"})

    assert result == {"provider": "fallback"}


def test_llms_requires_api_key(monkeypatch):
    monkeypatch.delenv("COMMANDCODE_API_KEY", raising=False)

    with pytest.raises(llms.ModelConfigurationError):
        llms.create_chat_model(llms.ModelProfile.FAST)
