import pytest
from langchain_core.runnables import RunnableLambda

import app.agent.llms as llms


class FakeChatModel:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.structured_method = None
        self.instances.append(self)

    def with_structured_output(self, _schema, method="function_calling"):
        self.structured_method = method
        return RunnableLambda(lambda payload: payload)


def test_all_chat_models_share_primary_and_fallback(monkeypatch):
    FakeChatModel.instances.clear()
    monkeypatch.setenv("COMMANDCODE_API_KEY", "test-key")
    monkeypatch.setenv("COMMANDCODE_MODEL", "primary-model")
    monkeypatch.setenv("COMMANDCODE_MODEL_FALLBACK", "fallback-model")
    monkeypatch.setenv("COMMANDCODE_BASE_URL", "https://api.commandcode.ai/")
    monkeypatch.setattr(llms, "ChatOpenAI", FakeChatModel)

    llms.create_chat_model()

    assert [m.kwargs["model"] for m in FakeChatModel.instances] == ["primary-model", "fallback-model"]
    for model in FakeChatModel.instances:
        assert model.kwargs["api_key"] == "test-key"
        assert model.kwargs["base_url"] == "https://api.commandcode.ai/provider/v1"
        assert model.kwargs["temperature"] == 0


def test_structured_model_uses_fallback_after_primary_failure():
    class FailingModel:
        def with_structured_output(self, _schema, method="function_calling"):
            assert method == "json_mode"
            def fail(_payload):
                raise RuntimeError("primary unavailable")

            return RunnableLambda(fail)

    class WorkingModel:
        def with_structured_output(self, _schema, method="function_calling"):
            assert method == "json_mode"
            return RunnableLambda(lambda _payload: {"provider": "fallback"})

    model = llms.ChatModelWithFallback(FailingModel(), WorkingModel())

    result = model.with_structured_output(dict).invoke({"question": "test"})

    assert result == {"provider": "fallback"}


def test_structured_model_uses_json_content_instead_of_tool_calls():
    model = FakeChatModel()
    llms.ChatModelWithFallback(model).with_structured_output(dict)
    assert model.structured_method == "json_mode"


def test_tool_call_uses_fallback_after_primary_failure():
    class ToolModel:
        def __init__(self, fail):
            self.fail = fail

        def bind_tools(self, tools):
            assert tools == ["tool"]
            def invoke(payload):
                if self.fail:
                    raise RuntimeError("primary unavailable")
                return {"tool_calls": ["fallback"]}
            return RunnableLambda(invoke)

    model = llms.ChatModelWithFallback(ToolModel(True), ToolModel(False))
    assert model.bind_tools(["tool"]).invoke("question") == {"tool_calls": ["fallback"]}


def test_llms_requires_api_key(monkeypatch):
    monkeypatch.delenv("COMMANDCODE_API_KEY", raising=False)

    with pytest.raises(llms.ModelConfigurationError):
        llms.create_chat_model()
