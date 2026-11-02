"""Mede onde o /chat gasta tempo: por etapa, por especialista e por chamada de IA.

Roda o grafo direto (sem HTTP), com o rastreamento de telemetria, e não grava nada no MongoDB. Usa as
variáveis do ambiente (o `.env` é carregado pela própria aplicação).

    python scripts/perfil_chat.py                       # todos os cenários, uma vez
    python scripts/perfil_chat.py -c quimico-cloro-amonia -n 3
    python scripts/perfil_chat.py --saida perfil.json
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.agent.workflow import run_chat  # noqa: E402
from app.observability.telemetry import Trace, current  # noqa: E402
from app.agent.guardrails.input_guardrail import INPUT_SAFE_RESPONSE  # noqa: E402
from tests.cenarios_chat import CENARIOS, Cenario, avaliar, por_id  # noqa: E402

ETAPAS = ("guardrail_entrada", "orquestrador", "especialistas", "juiz", "guardrail_saida")


async def executar(cenario: Cenario, limite: float) -> dict:
    trace = Trace("chat")
    token = current.set(trace)
    inicio = time.perf_counter()
    resultado = {"id": cenario.id, "dominio": cenario.dominio}
    try:
        resposta = await asyncio.wait_for(run_chat(cenario.pergunta, str(uuid.uuid4())), timeout=limite)
        resultado.update(status="ok", agentes=resposta.agentes_acionados, chars=len(resposta.resposta),
                         resposta=resposta.resposta,
                         problemas=avaliar(cenario, resposta.resposta, resposta.agentes_acionados, INPUT_SAFE_RESPONSE))
    except Exception as erro:  # o perfil precisa sobreviver a falhas para mostrá-las
        resultado.update(status=type(erro).__name__, erro=str(erro)[:200])
    finally:
        resultado["total_s"] = round(time.perf_counter() - inicio, 2)
        current.reset(token)
    resultado["etapas_s"] = {
        span["name"]: round(span["duration_ms"] / 1000, 2) for span in trace.spans if span["kind"] == "stage"
    }
    resultado["agentes_s"] = {
        span["name"]: round(span["duration_ms"] / 1000, 2) for span in trace.spans if span["kind"] == "agent"
    }
    resultado["chamadas"] = [
        {
            "modelo": call.get("model"),
            "etapa": call.get("stage"),
            "s": round((call.get("duration_ms") or 0) / 1000, 2),
            "tokens_in": call.get("input_tokens"),
            "tokens_out": call.get("output_tokens"),
            "erro": call.get("error"),
        }
        for call in trace.calls
    ]
    return resultado


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, round(p * (len(ordenados) - 1)))]


def imprimir(resultados: list[dict]) -> None:
    cabecalho = f"{'cenário':<24}{'status':<10}{'total':>7}" + "".join(f"{e[:9]:>11}" for e in ETAPAS) + f"{'IA':>5}"
    print(cabecalho)
    print("-" * len(cabecalho))
    for r in resultados:
        etapas = "".join(f"{r['etapas_s'].get(e, 0):>11.1f}" for e in ETAPAS)
        print(f"{r['id']:<24}{r['status'][:9]:<10}{r['total_s']:>7.1f}{etapas}{len(r['chamadas']):>5}")
    com_problema = [r for r in resultados if r.get("problemas")]
    print(f"\nqualidade: {len(resultados) - len(com_problema)}/{len(resultados)} cenários sem problemas objetivos")
    for r in com_problema:
        print(f"  {r['id']}: {'; '.join(r['problemas'])}")
    totais = [r["total_s"] for r in resultados if r["status"] == "ok"]
    if totais:
        print(f"\nok={len(totais)}/{len(resultados)}  p50={statistics.median(totais):.1f}s  "
              f"p95={percentil(totais, 0.95):.1f}s  máx={max(totais):.1f}s")
    lentas = sorted((c for r in resultados for c in r["chamadas"]), key=lambda c: -c["s"])[:5]
    print("\nchamadas de IA mais lentas:")
    for c in lentas:
        print(f"  {c['s']:>6.1f}s  {c['etapa'] or '-':<18} {c['modelo']}  in={c['tokens_in']} out={c['tokens_out']}")


async def principal() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--cenario", action="append", help="id do cenário (repetível); padrão: todos")
    parser.add_argument("-n", "--repeticoes", type=int, default=1)
    parser.add_argument("--limite", type=float, default=120, help="tempo máximo por pergunta, em segundos")
    parser.add_argument("--saida", help="grava o resultado completo em JSON")
    parser.add_argument("--mostrar", action="store_true", help="imprime a resposta de cada cenário")
    args = parser.parse_args()

    cenarios = por_id(*args.cenario) if args.cenario else CENARIOS
    resultados = []
    for _ in range(args.repeticoes):
        for cenario in cenarios:  # em série, para um cenário não atrapalhar a medida do outro
            resultados.append(await executar(cenario, args.limite))
            ultimo = resultados[-1]
            print(f"  {ultimo['id']}: {ultimo['status']} em {ultimo['total_s']}s", flush=True)
            if args.mostrar and ultimo.get("resposta"):
                print(f"    -> {ultimo['resposta']}\n", flush=True)
    print()
    imprimir(resultados)
    if args.saida:
        Path(args.saida).write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nresultado completo em {args.saida}")


if __name__ == "__main__":
    asyncio.run(principal())
