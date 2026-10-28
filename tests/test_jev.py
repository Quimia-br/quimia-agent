import io
import json

import pytest
from pydantic import ValidationError

import app.agent.jev as jev
from app.agent.contracts import SynthesisResult


def answers(choice="apoiada", support=0.9, risk=0.0, leak=0.0, proximity=0.0):
    return jev.JevAnswers.model_validate({
        "apoio": {"type": "choice", "choice": choice, "confidence": 0.9},
        "apoio_total": {"type": "noul", "noul": support},
        "risco_quimico": {"type": "noul", "noul": risk},
        "vazamento": {"type": "noul", "noul": leak},
        "proximidade": {"type": "noul", "noul": proximity},
    })


def test_jev_request_uses_systemone_and_pinned_model(monkeypatch):
    received = {}

    def fake_urlopen(request, timeout):
        received["url"] = request.full_url
        received["authorization"] = request.get_header("Authorization")
        received["timeout"] = timeout
        received["body"] = json.loads(request.data)
        return io.BytesIO(json.dumps({"answers": answers().model_dump()}).encode())

    monkeypatch.setattr(jev, "urlopen", fake_urlopen)
    client = jev.JevClient(api_key="test-key")
    result = client.decide({"pergunta": "Pergunta", "resposta": "Resposta"})

    assert received["url"] == "https://api.commandcode.ai/provider/v1/systemone"
    assert received["authorization"] == "Bearer test-key"
    assert received["body"]["model"] == "typesafe/jev-1.14.0"
    assert received["body"]["questions"]["apoio"]["type"] == "choice"
    assert received["body"]["questions"]["apoio_total"]["type"] == "noul"
    assert result.apoio.choice == "apoiada"


def test_jev_state_includes_clarification_before_judgment():
    state = jev.build_state("Qual produto?", SynthesisResult(
        resposta="Preciso identificar o produto.", esclarecer="Qual é o nome?"), [], [])
    assert state["resposta"] == "Preciso identificar o produto. Qual é o nome?"


@pytest.mark.parametrize("support, verdict", [(0.70, "aprovado"), (0.69, "bloqueado")])
def test_jev_support_threshold(support, verdict):
    assert jev.to_judge_result(answers(support=support)).veredito == verdict


def test_jev_partial_requests_one_existing_revision():
    result = jev.to_judge_result(answers(choice="parcial", support=0.5))
    assert result.veredito == "revisar"
    assert result.correcoes_necessarias


def test_jev_safety_risk_overrides_factual_support():
    result = jev.to_judge_result(answers(risk=0.8))
    assert result.veredito == "bloqueado"
    assert result.riscos_seguranca


def test_jev_proximity_requests_revision():
    assert jev.to_judge_result(answers(proximity=0.8)).veredito == "revisar"


def test_jev_rejects_missing_or_invalid_answers():
    with pytest.raises(ValidationError):
        jev.JevAnswers.model_validate({"apoio": {"type": "choice", "choice": "unknown", "confidence": 1}})


def test_jev_requires_real_api_key_not_base_url(monkeypatch):
    monkeypatch.delenv("COMMANDCODE_API_KEY", raising=False)
    with pytest.raises(jev.JevConfigurationError):
        jev.JevClient()
