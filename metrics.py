"""Prometheus metrics exported at /metrics.

Alert rules in deploy/prometheus/alerts.yml watch the safety signals: any
unsupported figure, falling claim support, abstention spikes, provider
fallbacks and open circuits.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

ANSWERS = Counter("carina_answers_total", "Answers by status and provider", ["status", "provider"])
ABSTENTIONS = Counter("carina_abstentions_total", "Abstentions by reason", ["reason"])
EMERGENCIES = Counter("carina_emergencies_total", "Emergency triage matches by category", ["category"])
TOOL_CALLS = Counter("carina_tool_calls_total", "Deterministic tool runs", ["tool", "status"])
REDACTIONS = Counter("carina_redactions_total", "Identifiers redacted from questions")
INJECTIONS_DROPPED = Counter("carina_injection_chunks_dropped_total", "Retrieved passages dropped by the injection filter")
UNSUPPORTED_FIGURES = Counter("carina_unsupported_figures_total", "Clinical figures in answers not found in cited sources")
PROVIDER_FALLBACKS = Counter("carina_provider_fallbacks_total", "Providers skipped or failed before an answer", ["provider"])
CACHE_HITS = Counter("carina_cache_hits_total", "Answer cache hits")
FEEDBACK = Counter("carina_feedback_total", "Clinician feedback", ["rating"])

CITATION_COVERAGE = Histogram("carina_citation_coverage", "Share of factual sentences with a valid citation", buckets=(0.5, 0.7, 0.8, 0.9, 0.95, 1.0))
CLAIM_SUPPORT = Histogram("carina_claim_support", "Share of cited claims supported by their sources", buckets=(0.5, 0.7, 0.8, 0.9, 0.95, 1.0))
REQUEST_LATENCY = Histogram("carina_request_seconds", "End to end answer latency", buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32))
STAGE_LATENCY = Histogram("carina_stage_seconds", "Latency by pipeline stage", ["stage"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16))
