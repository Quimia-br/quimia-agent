"""Cálculos auditáveis de SLI, custo e projeções; valores ausentes não viram zero."""

import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path

from app.observability.telemetry import in_progress


def pricing():
    data = json.loads(Path(__file__).with_name("pricing.json").read_text(encoding="utf-8"))
    overrides = json.loads(os.getenv("SRE_PRICING_JSON", "{}"))
    for model, rates in overrides.items():
        for key in ("input", "output"):
            value = rates[key]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("SRE_PRICING_JSON exige preços finitos e não negativos.")
        data["models"][model] = rates
    return data


def percentile(values, q):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(q * len(values)) - 1)]


def average(values):
    return sum(values) / len(values) if values else None


def call_cost(call, rates):
    if "estimated_cost_usd" in call:
        return call["estimated_cost_usd"]
    rate = rates.get(call["model"])
    input_tokens, output_tokens = call.get("input_tokens"), call.get("output_tokens")
    if rate is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1_000_000


def snapshot(records, *, days=7, turns_per_user=5, minutes_saved=None, hourly_cost=None,
             fixed_weekly_cost=0, assumed_resolution_rate=0.7,
             planned_input_tokens=10000, planned_output_tokens=2000,
             truncated=False):
    prices = pricing()
    rates = prices["models"]
    stages = defaultdict(lambda: {"durations": [], "errors": 0})
    models = defaultdict(lambda: {"calls": 0, "errors": 0, "input_tokens": 0,
                                  "output_tokens": 0, "cost_usd": 0, "missing_usage": 0})
    calls = []
    missing_usage = 0
    total_cost = 0
    fallback_calls = 0
    traces = []
    for record in records:
        cost = 0
        unknown = 0
        for call in record["calls"]:
            calls.append(call)
            amount = call_cost(call, rates)
            unknown += amount is None
            cost += amount or 0
            row = models[call["model"]]
            row["calls"] += 1
            row["errors"] += bool(call.get("error"))
            row["input_tokens"] += call.get("input_tokens") or 0
            row["output_tokens"] += call.get("output_tokens") or 0
            row["cost_usd"] += amount or 0
            row["missing_usage"] += amount is None
            fallback_calls += bool(call.get("fallback"))
        total_cost += cost
        missing_usage += unknown
        for s in record["spans"]:
            row = stages[(s["kind"], s["name"])]
            row["durations"].append(s["duration_ms"])
            row["errors"] += bool(s["error"])
        top = sorted([s for s in record["spans"] if s["kind"] == "stage"], key=lambda s: s["start_ms"])
        handoffs = [{"from": a["name"], "to": b["name"],
                     "gap_ms": max(0, b["start_ms"] - a["start_ms"] - a["duration_ms"])}
                    for a, b in zip(top, top[1:])]
        traces.append({**record, "known_cost_usd": cost, "cost_partial": bool(unknown), "handoffs": handoffs})
    chats = [r for r in records if r.get("operation", "chat") == "chat"]
    summaries = [r for r in records if r.get("operation") == "session_summary"]
    n = len(chats)
    errors = sum(r["http_status"] >= 500 or r["degraded"] for r in chats)
    durations = [r["duration_ms"] for r in chats]
    p95 = percentile(durations, .95)
    error_rate = errors / n if n else None
    latency_limit = float(os.getenv("SRE_LATENCY_P95_MS", "8000"))
    error_limit = float(os.getenv("SRE_ERROR_RATE_LIMIT", "0.05"))
    confirmations = [r for r in chats if r.get("resolved") is not None]
    resolved = sum(r.get("resolved") is True for r in chats)
    value = minutes_saved * hourly_cost / 60 if minutes_saved is not None and hourly_cost is not None else None
    period_cost = total_cost + fixed_weekly_cost * days / 7
    benefit = resolved * value if value is not None and confirmations else None
    observed_mean_cost = total_cost / n if n and calls else None
    primary = os.getenv("COMMANDCODE_MODEL", "xiaomi/mimo-v2.6-flash")
    plan_rate = rates.get(primary)
    planned_cost = ((planned_input_tokens * plan_rate["input"] + planned_output_tokens * plan_rate["output"]) / 1_000_000
                    if plan_rate else None)
    per_turn = observed_mean_cost if observed_mean_cost is not None else planned_cost
    basis = "observed" if observed_mean_cost is not None else "planning"
    resolution_rate = resolved / n if n and confirmations else assumed_resolution_rate
    scenarios = []
    for users in (100, 1000):
        turns = users * turns_per_user
        cost = turns * per_turn + fixed_weekly_cost if per_turn is not None else None
        resolutions = turns * resolution_rate
        savings = resolutions * value if value is not None else None
        scenarios.append({"weekly_users": users, "weekly_turns": turns,
            "estimated_cost_usd": cost, "estimated_resolutions": resolutions,
            "cost_per_resolution_usd": cost / resolutions if cost is not None and resolutions else None,
            "estimated_benefit_usd": savings,
            "roi": (savings - cost) / cost if savings is not None and cost else None,
            "net_return_usd": savings - cost if savings is not None and cost is not None else None})
    return {
        "generated_at": time.time(), "window_days": days, "truncated": truncated,
        "pricing": prices,
        "summary": {"requests": n, "errors": errors, "error_rate": error_rate,
            "session_summary_requests": len(summaries),
            "session_summary_errors": sum(r["http_status"] >= 500 for r in summaries),
            "validation_errors": sum(r["http_status"] == 422 for r in records),
            "latency_mean_ms": average(durations), "latency_p50_ms": percentile(durations,.5),
            "latency_p95_ms": p95, "latency_p99_ms": percentile(durations,.99),
            "in_progress_this_process": in_progress(), "fallback_calls": fallback_calls,
            "fallback_turns": sum(any(c.get("fallback") for c in r["calls"]) for r in records),
            "blocked_input": sum(r["outcome"] == "bloqueado_entrada" for r in records),
            "blocked_output": sum(r["outcome"] == "bloqueado_saida" for r in records),
            "judge_rejected": sum(r["outcome"] == "nao_aprovado" for r in records),
            "faq_no_evidence": sum(r["outcome"] == "sem_evidencias" for r in records),
            "known_cost_usd": total_cost, "cost_partial": missing_usage > 0,
            "unpriced_or_unknown_calls": missing_usage,
            "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "cost_coverage": (len(calls) - missing_usage) / len(calls) if calls else None,
            "confirmed_resolutions": resolved, "feedback_count": len(confirmations),
            "feedback_coverage": len(confirmations) / n if n else None,
            "cost_per_resolution_usd": period_cost / resolved if resolved else None,
            "benefit_usd": benefit,
            "roi": (benefit - period_cost) / period_cost if benefit is not None and period_cost else None},
        "slo": {"p95_limit_ms": latency_limit, "error_rate_limit": error_limit,
            "ok": p95 <= latency_limit and error_rate <= error_limit if n else None,
            "error_budget_remaining_requests": max(0, n * error_limit - errors) if n else None},
        "by_stage": [{"kind": kind, "name": name, "calls": len(row["durations"]),
                      "errors": row["errors"], "mean_ms": average(row["durations"]),
                      "p95_ms": percentile(row["durations"],.95)} for (kind,name),row in stages.items()],
        "by_model": [{"model": model, **row} for model,row in models.items()],
        "scenarios": scenarios,
        "assumptions": {"currency": "USD", "cost_basis": basis,
            "turns_per_user_week": turns_per_user, "minutes_saved_per_resolution": minutes_saved,
            "hourly_cost_usd": hourly_cost, "fixed_weekly_cost_usd": fixed_weekly_cost,
            "resolution_rate": resolution_rate, "resolution_rate_basis": "confirmed_over_all_requests" if confirmations else "assumed",
            "planned_input_tokens_per_turn": planned_input_tokens, "planned_output_tokens_per_turn": planned_output_tokens,
            "note": "Planejamento sem amostras considera somente tokens de chat do modelo principal, sem JEV, embeddings ou fallback. Custos observados podem ser parciais; chamadas sem usage/preço não são gratuitas. Custos fixos são informados pelo operador. Resolução é uma confirmação por turno, não uma nota do juiz."},
        "traces": traces[:100],
    }
