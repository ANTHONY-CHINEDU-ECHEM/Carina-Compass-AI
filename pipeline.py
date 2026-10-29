"""The question answering pipeline.

  redact -> triage -> understand -> scope -> tools -> retrieve -> injection filter
  -> answerability gate -> generate (router with fallbacks) -> validate citations
  -> check figures -> check claim support -> audit

`ask` returns a complete answer; `stream` yields typed server sent events in
the same order: meta, emergency, tools, sources, token..., final.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from carina.audit import AuditLog
from carina.cache import AnswerCache, cache_key
from carina.clinical import tool_router
from carina.clinical.understanding import QueryUnderstanding, understand
from carina.config import Settings
from carina.domain import PatientContext, ScoredChunk
from carina.generation import answerability, citations, faithfulness
from carina.generation.prompts import ABSTAIN_TOKEN, SYSTEM_PROMPT, build_user_prompt
from carina.guardrails import emergency, pii, scope
from carina.guardrails.injection import looks_like_injection
from carina.llm.base import GenerationRequest, ProviderError
from carina.llm.router import ProviderRouter
from carina.observability import metrics
from carina.retrieval.hybrid import HybridRetriever
from carina.retrieval.supersession import notes as supersession_notes
from carina.retrieval.supersession import primary_reference, superseding

log = logging.getLogger(__name__)

ABSTAIN_MESSAGE = (
    "The indexed evidence is not strong or specific enough to answer this safely. "
    "Please refine the question (histology, stage, biomarkers, line of therapy) or consult the full NICE guidance and the MDT."
)


@dataclass
class Prepared:
    request_id: str
    question: str
    redaction: pii.RedactionResult
    alerts: list[emergency.EmergencyAlert]
    understanding: QueryUnderstanding
    context: PatientContext
    in_scope: bool
    scope_reason: str
    tool_cards: list[tool_router.ToolCard]
    results: list[ScoredChunk] = field(default_factory=list)
    dropped_injections: int = 0
    answerable: answerability.Answerability | None = None
    retrieval_query: str = ""
    started: float = field(default_factory=time.perf_counter)


@dataclass
class AskResult:
    request_id: str
    answer: str
    status: str  # answered, abstained, out_of_scope, emergency_only
    provider: str | None
    model: str | None
    fallbacks_used: list[str]
    emergencies: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    understanding: dict[str, Any]
    redactions: dict[str, int]
    citation_report: dict[str, Any] | None
    faithfulness: dict[str, Any] | None
    answerability: dict[str, Any] | None
    grounded: bool
    latency_ms: int
    cached: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def source_cards(results: list[ScoredChunk]) -> list[dict[str, Any]]:
    cards = []
    for idx, item in enumerate(results, start=1):
        chunk = item.chunk
        replaced = superseding(chunk)
        cards.append(
            {
                "id": idx,
                "chunk_id": chunk.chunk_id,
                "title": chunk.title,
                "section": chunk.section,
                "url": chunk.url,
                "source": chunk.source.value,
                "evidence_grade": int(chunk.evidence_grade),
                "evidence_label": chunk.evidence_grade.label,
                "year": chunk.year,
                "jurisdiction": chunk.jurisdiction.value,
                "licence": chunk.licence_key,
                "identifiers": chunk.identifiers,
                "superseded_by": replaced,
                "score": round(item.final_score, 4),
                "excerpt": chunk.text[:420] + ("..." if len(chunk.text) > 420 else ""),
            }
        )
    return cards


class RAGPipeline:
    def __init__(self, settings: Settings, retriever: HybridRetriever, router: ProviderRouter, audit: AuditLog, cache: AnswerCache) -> None:
        self.settings = settings
        self.retriever = retriever
        self.router = router
        self.audit = audit
        self.cache = cache
        self.known_terms = scope.known_terms_from_index(retriever.index.documents.values())

    # Preparation shared by ask and stream
    def prepare(self, question: str, context: PatientContext | None = None, history_in_scope: bool = False) -> Prepared:
        request_id = uuid.uuid4().hex[:16]
        redaction = pii.redact(question)
        clean = redaction.text
        alerts = emergency.triage(clean)
        qu = understand(clean)
        ctx = qu.to_patient_context(context)
        # Clinical context supplied with the question puts a terse question ("first line options?") in scope.
        contextual = history_in_scope or bool(context and not context.is_empty())
        decision = scope.check_scope(clean, qu, contextual, self.known_terms)
        in_scope = decision.in_scope or bool(alerts)
        cards = tool_router.route(qu, ctx, self.retriever.index.trials) if (in_scope and self.settings.tool_routing) else []
        prepared = Prepared(request_id, clean, redaction, alerts, qu, ctx, in_scope, decision.reason, cards)
        for alert in alerts:
            metrics.EMERGENCIES.labels(alert.category).inc()
        for card in cards:
            metrics.TOOL_CALLS.labels(card.tool, card.status).inc()
        if redaction.redacted:
            metrics.REDACTIONS.inc(sum(redaction.counts.values()))
        if not in_scope:
            return prepared

        query = qu.retrieval_query()
        if alerts:
            query += " " + " ".join(a.retrieval_hint() for a in alerts)
        prepared.retrieval_query = query
        with metrics.STAGE_LATENCY.labels("retrieval").time():
            retrieved = self.retriever.retrieve(
                query,
                biomarkers=qu.biomarkers or ctx.biomarkers,
                setting=qu.setting or ctx.setting,
                histology=qu.histology or ctx.histology,
                rerank_query=qu.precision_query(),
                expansions=" ".join(qu.expansions),
                prefer_results="evidence" in qu.intents,
            )
        kept = []
        for item in retrieved.results:
            if looks_like_injection(item.chunk.text):
                prepared.dropped_injections += 1
                metrics.INJECTIONS_DROPPED.inc()
                continue
            kept.append(item)
        prepared.results = kept
        prepared.answerable = answerability.assess(
            clean,
            kept,
            self.retriever.index.bm25.idf,
            min_score=self.settings.min_evidence_score,
            min_coverage=self.settings.min_query_coverage,
            required_entities=qu.drugs,
            expansions=qu.expansions,
        )
        return prepared

    def _context_summary(self, ctx: PatientContext) -> str | None:
        fields = {
            "histology": ctx.histology,
            "stage group": ctx.stage_group,
            "TNM": " ".join(x for x in (ctx.t_category, ctx.n_category, ctx.m_category) if x) or None,
            "biomarkers": ", ".join(ctx.biomarkers) or None,
            "PD L1 TPS": f"{ctx.pdl1_tps:g}%" if ctx.pdl1_tps is not None else None,
            "performance status": ctx.performance_status,
            "setting": ctx.setting,
            "prior treatments": ", ".join(ctx.prior_treatments) or None,
        }
        lines = [f"{k}: {v}" for k, v in fields.items() if v not in (None, "")]
        return "\n".join(lines) or None

    def _request(self, prepared: Prepared) -> GenerationRequest:
        notes = []
        for item in prepared.results:
            if item.superseded:
                ref = primary_reference(item.chunk)
                note = supersession_notes().get(ref or "", f"{item.chunk.title} has been superseded.")
                if note not in notes:
                    notes.append(note)
        return GenerationRequest(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(prepared.question, prepared.results, self._context_summary(prepared.context), notes),
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_temperature,
            passages=[(idx, item.chunk.text) for idx, item in enumerate(prepared.results, start=1)],
            passage_weights={idx: 1.0 + 0.08 * int(item.chunk.evidence_grade) for idx, item in enumerate(prepared.results, start=1)},
            query=prepared.understanding.retrieval_query(),
            setting=prepared.understanding.setting or prepared.context.setting,
            biomarkers=list(prepared.context.biomarkers),
            drugs=list(prepared.understanding.drugs),
            titles={idx: item.chunk.title for idx, item in enumerate(prepared.results, start=1)},
            superseded={idx: superseding(item.chunk) or "" for idx, item in enumerate(prepared.results, start=1) if item.superseded},
            pdl1_tps=prepared.context.pdl1_tps,
        )

    def _finalise(self, prepared: Prepared, raw: str, provider: str | None, model: str | None, fallbacks: list[str], cached: bool = False) -> AskResult:
        sources = {idx: item.chunk.text for idx, item in enumerate(prepared.results, start=1)}
        status = "answered"
        report = None
        faith = None
        grounded = False
        text = raw.strip()
        if text == ABSTAIN_TOKEN or text.startswith(ABSTAIN_TOKEN):
            status = "abstained"
            text = ABSTAIN_MESSAGE
            metrics.ABSTENTIONS.labels("model").inc()
        else:
            report = citations.validate(text, sources)
            text = citations.flag_unsupported(report.text, report.unsupported_figures)
            faith_report = faithfulness.assess(report.text, sources, self.retriever.index.bm25.idf)
            faith = faith_report.as_dict()
            grounded = (
                report.coverage >= self.settings.min_citation_coverage and report.figures_ok and faith_report.claim_support >= self.settings.min_faithfulness
            )
            metrics.CITATION_COVERAGE.observe(report.coverage)
            metrics.CLAIM_SUPPORT.observe(faith_report.claim_support)
            if report.unsupported_figures:
                metrics.UNSUPPORTED_FIGURES.inc(len(report.unsupported_figures))
        latency = int((time.perf_counter() - prepared.started) * 1000)
        result = AskResult(
            request_id=prepared.request_id,
            answer=text,
            status=status,
            provider=provider,
            model=model,
            fallbacks_used=fallbacks,
            emergencies=[a.as_dict() for a in prepared.alerts],
            tools=[c.as_dict() for c in prepared.tool_cards],
            sources=source_cards(prepared.results) if status == "answered" else [],
            understanding=prepared.understanding.as_dict(),
            redactions=prepared.redaction.counts,
            citation_report=report.as_dict() if report else None,
            faithfulness=faith,
            answerability=prepared.answerable.as_dict() if prepared.answerable else None,
            grounded=grounded,
            latency_ms=latency,
            cached=cached,
        )
        metrics.ANSWERS.labels(status, provider or "none").inc()
        metrics.REQUEST_LATENCY.observe(latency / 1000)
        self.audit.record(prepared.question, result)
        return result

    def _short_circuit(self, prepared: Prepared) -> AskResult | None:
        if not prepared.in_scope:
            metrics.ABSTENTIONS.labels("scope").inc()
            return self._scope_result(prepared)
        answerable = prepared.answerable
        if answerable and not answerable.answerable:
            metrics.ABSTENTIONS.labels("evidence").inc()
            status = "emergency_only" if prepared.alerts else "abstained"
            latency = int((time.perf_counter() - prepared.started) * 1000)
            message = ABSTAIN_MESSAGE
            if any(card.status == "ok" for card in prepared.tool_cards):
                message += " The deterministic tool results for this question are shown separately and do not depend on the indexed evidence."
            result = AskResult(
                request_id=prepared.request_id,
                answer=message,
                status=status,
                provider=None,
                model=None,
                fallbacks_used=[],
                emergencies=[a.as_dict() for a in prepared.alerts],
                tools=[c.as_dict() for c in prepared.tool_cards],
                sources=[],
                understanding=prepared.understanding.as_dict(),
                redactions=prepared.redaction.counts,
                citation_report=None,
                faithfulness=None,
                answerability=answerable.as_dict(),
                grounded=False,
                latency_ms=latency,
            )
            metrics.ANSWERS.labels(status, "none").inc()
            self.audit.record(prepared.question, result)
            return result
        return None

    def _scope_result(self, prepared: Prepared) -> AskResult:
        latency = int((time.perf_counter() - prepared.started) * 1000)
        result = AskResult(
            request_id=prepared.request_id,
            answer=scope.OUT_OF_SCOPE_MESSAGE,
            status="out_of_scope",
            provider=None,
            model=None,
            fallbacks_used=[],
            emergencies=[],
            tools=[],
            sources=[],
            understanding=prepared.understanding.as_dict(),
            redactions=prepared.redaction.counts,
            citation_report=None,
            faithfulness=None,
            answerability=None,
            grounded=False,
            latency_ms=latency,
        )
        metrics.ANSWERS.labels("out_of_scope", "none").inc()
        self.audit.record(prepared.question, result)
        return result

    async def ask(self, question: str, context: PatientContext | None = None, provider: str | None = None, history_in_scope: bool = False) -> AskResult:
        prepared = self.prepare(question, context, history_in_scope)
        short = self._short_circuit(prepared)
        if short is not None:
            return short
        key = cache_key(prepared.question, prepared.context.model_dump(), provider or self.settings.llm_provider)
        hit = await self.cache.get(key)
        if hit is not None and not prepared.alerts:
            metrics.CACHE_HITS.inc()
            return self._finalise(prepared, hit["raw"], hit["provider"], hit["model"], [], cached=True)
        request = self._request(prepared)
        try:
            with metrics.STAGE_LATENCY.labels("generation").time():
                generated, skipped = await self.router.generate(request, provider or self.settings.llm_provider)
        except ProviderError:
            return self._finalise(prepared, ABSTAIN_TOKEN, None, None, ["all"])
        for name in skipped:
            metrics.PROVIDER_FALLBACKS.labels(name).inc()
        await self.cache.set(key, {"raw": generated.text, "provider": generated.provider, "model": generated.model})
        return self._finalise(prepared, generated.text, generated.provider, generated.model, skipped)

    async def stream(
        self, question: str, context: PatientContext | None = None, provider: str | None = None, history_in_scope: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        prepared = self.prepare(question, context, history_in_scope)
        yield {
            "event": "meta",
            "data": {"request_id": prepared.request_id, "redactions": prepared.redaction.counts, "understanding": prepared.understanding.as_dict()},
        }
        if prepared.alerts:
            yield {"event": "emergency", "data": [a.as_dict() for a in prepared.alerts]}
        if prepared.tool_cards:
            yield {"event": "tools", "data": [c.as_dict() for c in prepared.tool_cards]}
        short = self._short_circuit(prepared)
        if short is not None:
            yield {"event": "final", "data": short.as_dict()}
            return
        yield {"event": "sources", "data": source_cards(prepared.results)}
        request = self._request(prepared)
        pieces: list[str] = []
        try:
            routed, iterator = await self.router.stream(request, provider or self.settings.llm_provider)
            for name in routed.fallbacks_used:
                metrics.PROVIDER_FALLBACKS.labels(name).inc()
            buffer = ""
            async for piece in iterator:
                pieces.append(piece)
                buffer += piece
                # Hold back anything that might be the abstain token so it is never shown raw.
                if ABSTAIN_TOKEN.startswith(buffer.strip()) and len(buffer.strip()) < len(ABSTAIN_TOKEN):
                    continue
                if buffer.strip() == ABSTAIN_TOKEN:
                    continue
                yield {"event": "token", "data": buffer}
                buffer = ""
            if buffer and buffer.strip() != ABSTAIN_TOKEN:
                yield {"event": "token", "data": buffer}
            result = self._finalise(prepared, "".join(pieces), routed.provider, routed.model, routed.fallbacks_used)
        except ProviderError:
            result = self._finalise(prepared, ABSTAIN_TOKEN, None, None, ["all"])
        yield {"event": "final", "data": result.as_dict()}
