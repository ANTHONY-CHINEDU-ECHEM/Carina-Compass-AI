"""Evaluation harness.

  carina-eval                 offline run on the seed index with the extractive generator (what CI runs)
  carina-eval live            run against the configured index and model provider
  carina-eval gate            offline run, then fail with exit code 1 if any threshold in thresholds.yaml is missed

Every question in golden_set.jsonl names the sources that should be
retrieved, the facts the answer should contain, the deterministic tools that
should fire, the emergency category expected (if any) and the expected status
(answered, abstained, out_of_scope, or any when only the safety layers are
being tested).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from evaluation import metrics

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden_set.jsonl"
THRESHOLDS = HERE / "thresholds.yaml"
REPORTS = HERE / "reports"


def load_golden(path: Path = GOLDEN) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _offline_environment() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="carina-eval-"))
    os.environ.update(
        {
            "CC_LLM_PROVIDER": "extractive",
            "CC_LLM_FALLBACKS": "extractive",
            "CC_EMBEDDING_BACKEND": "hashing",
            "CC_RERANKER_BACKEND": "lexical",
            "CC_VECTOR_BACKEND": "memory",
            "CC_CACHE_BACKEND": "memory",
            "CC_INDEX_DIR": str(tmp / "no-index"),
            "CC_AUDIT_PATH": str(tmp / "audit.jsonl"),
            "CC_FEEDBACK_PATH": str(tmp / "feedback.jsonl"),
        }
    )


async def run(mode: str = "offline") -> dict[str, Any]:
    if mode == "offline":
        _offline_environment()
    from carina.config import get_settings
    from carina.container import build_container
    from carina.domain import PatientContext

    get_settings.cache_clear()
    container = build_container()
    rows = []
    for item in load_golden():
        ctx = PatientContext(**item["patient_context"]) if item.get("patient_context") else None
        prepared = container.pipeline.prepare(item["question"], ctx)
        retrieved = [r.chunk.chunk_id for r in prepared.results]
        result = await container.pipeline.ask(item["question"], ctx)
        status_ok = item["expected_status"] == "any" or result.status == item["expected_status"]
        emergencies = [e["category"] for e in result.emergencies]
        expected_emergency = item.get("expected_emergency")
        row = {
            "id": item["id"],
            "category": item["category"],
            "status": result.status,
            "expected_status": item["expected_status"],
            "status_ok": status_ok,
            "hit_at_5": metrics.hit_at_k(retrieved, item["expected_sources"], 5),
            "mrr": metrics.reciprocal_rank(retrieved, item["expected_sources"]),
            "fact_recall": metrics.fact_recall(result.answer, item["expected_facts"])
            if result.status == "answered"
            else (0.0 if item["expected_facts"] else None),
            "coverage": (result.citation_report or {}).get("coverage") if result.status == "answered" else None,
            "unsupported_figures": len((result.citation_report or {}).get("unsupported_figures", [])) if result.status == "answered" else 0,
            "claim_support": (result.faithfulness or {}).get("claim_support") if result.status == "answered" else None,
            "tool_routing": metrics.tool_routing(result.tools, item["expected_tools"]),
            "emergency_ok": (expected_emergency in emergencies) if expected_emergency else (not emergencies),
            "redaction_ok": all(k in result.redactions for k in (item.get("expected_redactions") or [])),
            "provider": result.provider,
            "latency_ms": result.latency_ms,
        }
        rows.append(row)

    def subset(category: str | None = None, field: str = "") -> list[Any]:
        return [r[field] for r in rows if category is None or r["category"] == category]

    abstention_rows = [r for r in rows if r["expected_status"] in ("abstained", "out_of_scope") or r["category"] == "abstention"]
    scope_rows = [r for r in rows if r["category"] == "scope" or r["expected_status"] == "out_of_scope"]
    answer_rows = [r for r in rows if r["expected_status"] == "answered"]
    summary = {
        "mode": mode,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "questions": len(rows),
        "retrieval_hit_at_5": metrics.mean(subset(field="hit_at_5")),
        "retrieval_mrr": metrics.mean(subset(field="mrr")),
        "expected_fact_recall": metrics.mean([r["fact_recall"] for r in answer_rows]),
        "citation_coverage": metrics.mean([r["coverage"] for r in answer_rows]),
        "claim_support": metrics.mean([r["claim_support"] for r in answer_rows]),
        "answers_with_unsupported_figure": metrics.mean([1.0 if r["unsupported_figures"] else 0.0 for r in answer_rows]),
        "answered_when_expected": metrics.mean([1.0 if r["status"] == "answered" else 0.0 for r in answer_rows]),
        "emergency_triage_accuracy": metrics.mean([1.0 if r["emergency_ok"] else 0.0 for r in rows]),
        "abstention_accuracy": metrics.mean([1.0 if r["status_ok"] else 0.0 for r in abstention_rows]),
        "scope_accuracy": metrics.mean([1.0 if r["status_ok"] else 0.0 for r in scope_rows]),
        "tool_routing_accuracy": metrics.mean([r["tool_routing"] for r in rows]),
        "redaction_accuracy": metrics.mean([1.0 if r["redaction_ok"] else 0.0 for r in rows]),
        "status_accuracy": metrics.mean([1.0 if r["status_ok"] else 0.0 for r in rows]),
        "p50_latency_ms": sorted(r["latency_ms"] for r in rows)[len(rows) // 2],
    }
    return {"summary": summary, "rows": rows}


def check_gate(summary: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures = []
    for metric, rule in thresholds["gate"].items():
        value = summary.get(metric)
        if value is None:
            failures.append(f"{metric}: not measured")
            continue
        if "min" in rule and value < rule["min"]:
            failures.append(f"{metric}: {value} below minimum {rule['min']}")
        if "max" in rule and value > rule["max"]:
            failures.append(f"{metric}: {value} above maximum {rule['max']}")
    return failures


def write_report(result: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    mode = result["summary"]["mode"]
    path = REPORTS / f"{mode}_latest.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [f"# Evaluation report ({mode})", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in result["summary"].items()]
    lines += ["", "| Question | Status | Hit at 5 | Fact recall | Coverage | Claim support | Tools | Emergency |", "|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(
            f"| {r['id']} | {r['status']} | {r['hit_at_5']} | {r['fact_recall']} | {r['coverage']} | {r['claim_support']} | {r['tool_routing']} | {r['emergency_ok']} |"
        )
    (REPORTS / f"{mode}_latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carina-eval")
    parser.add_argument("command", nargs="?", default="offline", choices=["offline", "live", "gate"])
    args = parser.parse_args(argv)
    mode = "live" if args.command == "live" else "offline"
    result = asyncio.run(run(mode))
    write_report(result)
    print(json.dumps(result["summary"], indent=2))
    if args.command == "gate":
        thresholds = yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8"))
        failures = check_gate(result["summary"], thresholds)
        if failures:
            print("\nEvaluation gate FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("\nEvaluation gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
