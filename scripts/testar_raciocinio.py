"""Mede se o modelo gasta tokens de raciocínio e se dá para desligá-los (menos tokens = resposta mais rápida).

    python scripts/testar_raciocinio.py -m z-ai/glm-5.3-flash

Usa o prompt do Químico e uma pergunta de mistura, sem ferramentas, e compara variações dos parâmetros extras
aceitos pela Provider API. Cada variação roda `-n` vezes.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from app.agent.prompts import QUIMICO_PROMPT_COMPLETO  # noqa: E402
from app.core.config import carregar_config  # noqa: E402

VARIACOES = {
    "padrão": {},
    "thinking desligado": {"extra_body": {"thinking": {"type": "disabled"}}},
    "reasoning_effort baixo": {"extra_body": {"reasoning_effort": "low"}},
    "enable_thinking falso": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
}
PAYLOAD = {
    "pergunta_original": "Posso misturar água sanitária com amônia?",
    "objetivo": "Verificar a compatibilidade entre água sanitária e amônia.",
    "contexto_confirmado": "Nenhum dado confirmado disponível.",
    "resumo_conversa": "Não fornecido.",
}


def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-m", "--modelo", default="z-ai/glm-5.3-flash")
    parser.add_argument("-n", "--chamadas", type=int, default=3)
    args = parser.parse_args()
    config = carregar_config()
    print(f"{'variação':<26}{'ok':>3}{'mediana':>9}{'tokens saída':>14}{'raciocínio':>12}")
    for nome, extra in VARIACOES.items():
        tempos, saidas, raciocinio, erro = [], [], [], None
        for _ in range(args.chamadas):
            llm = ChatOpenAI(api_key=config.commandcode_api_key, base_url=config.commandcode_base_url,
                             model=args.modelo, temperature=0, timeout=60, max_retries=0, **extra)
            inicio = time.perf_counter()
            try:
                resposta = llm.invoke([SystemMessage(content=QUIMICO_PROMPT_COMPLETO),
                                       HumanMessage(content=json.dumps(PAYLOAD, ensure_ascii=False))])
            except Exception as falha:
                erro = f"{type(falha).__name__}: {str(falha)[:100]}"
                break
            tempos.append(time.perf_counter() - inicio)
            uso = resposta.usage_metadata or {}
            saidas.append(uso.get("output_tokens", 0))
            detalhes = (uso.get("output_token_details") or {})
            raciocinio.append(detalhes.get("reasoning", 0))
        if erro:
            print(f"{nome:<26}  erro: {erro}")
            continue
        print(f"{nome:<26}{len(tempos):>3}{statistics.median(tempos):>8.1f}s{statistics.median(saidas):>14.0f}"
              f"{statistics.median(raciocinio):>12.0f}", flush=True)


if __name__ == "__main__":
    principal()
