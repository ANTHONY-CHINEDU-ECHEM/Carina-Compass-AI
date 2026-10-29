"""Audit log, clinician feedback and the clinical governance summary.

Every answer is recorded with a keyed hash of the (already redacted) question,
never the text itself, alongside the sources used, the provider, coverage,
claim support and latency. Feedback comments are redacted before storage.
The governance summary gives the clinical safety officer the figures a
DCB0129 safety case review needs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from carina.guardrails.pii import redact


class AuditLog:
    def __init__(self, path: Path, feedback_path: Path, salt: str) -> None:
        self.path = path
        self.feedback_path = feedback_path
        self.salt = salt.encode()
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def question_hash(self, question: str) -> str:
        return hmac.new(self.salt, question.strip().lower().encode(), hashlib.sha256).hexdigest()[:24]

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, default=str)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def record(self, question: str, result: Any) -> None:
        superseded = sum(1 for s in result.sources if s.get("superseded_by"))
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "request_id": result.request_id,
            "question_hash": self.question_hash(question),
            "status": result.status,
            "provider": result.provider,
            "model": result.model,
            "fallbacks": result.fallbacks_used,
            "emergencies": [e["category"] for e in result.emergencies],
            "tools": [t["tool"] for t in result.tools],
            "source_ids": [s["chunk_id"] for s in result.sources],
            "superseded_sources": superseded,
            "coverage": (result.citation_report or {}).get("coverage"),
            "unsupported_figures": len((result.citation_report or {}).get("unsupported_figures", [])),
            "claim_support": (result.faithfulness or {}).get("claim_support"),
            "grounded": result.grounded,
            "redactions": result.redactions,
            "latency_ms": result.latency_ms,
            "cached": result.cached,
        }
        self._append(self.path, record)

    def feedback(self, request_id: str, rating: str, reasons: list[str], comment: str | None) -> dict[str, Any]:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "request_id": request_id,
            "rating": rating,
            "reasons": reasons,
            "comment": redact(comment).text if comment else None,
        }
        self._append(self.feedback_path, record)
        return record

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def summary(self) -> dict[str, Any]:
        rows = self._read(self.path)
        feedback = self._read(self.feedback_path)
        answered = [r for r in rows if r["status"] == "answered"]
        statuses = Counter(r["status"] for r in rows)
        emergencies = Counter(e for r in rows for e in r.get("emergencies", []))
        tools = Counter(t for r in rows for t in r.get("tools", []))
        providers = Counter(r.get("provider") or "none" for r in rows)
        ratings = Counter(f["rating"] for f in feedback)
        reasons = Counter(reason for f in feedback for reason in f.get("reasons", []))

        def mean(values: list[Any]) -> float | None:
            values = [v for v in values if v is not None]
            return round(sum(values) / len(values), 3) if values else None

        return {
            "questions": len(rows),
            "statuses": dict(statuses),
            "abstention_rate": round(statuses.get("abstained", 0) / len(rows), 3) if rows else None,
            "grounded_rate": round(sum(1 for r in answered if r.get("grounded")) / len(answered), 3) if answered else None,
            "mean_citation_coverage": mean([r.get("coverage") for r in answered]),
            "mean_claim_support": mean([r.get("claim_support") for r in answered]),
            "answers_with_unsupported_figures": sum(1 for r in answered if r.get("unsupported_figures")),
            "answers_citing_superseded_guidance": sum(1 for r in answered if r.get("superseded_sources")),
            "emergencies": dict(emergencies),
            "tool_use": dict(tools),
            "providers": dict(providers),
            "fallback_events": sum(1 for r in rows if r.get("fallbacks")),
            "feedback": {"ratings": dict(ratings), "reasons": dict(reasons), "count": len(feedback)},
            "p50_latency_ms": _percentile([r["latency_ms"] for r in rows], 50),
            "p95_latency_ms": _percentile([r["latency_ms"] for r in rows], 95),
        }


def _percentile(values: list[int], pct: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]
