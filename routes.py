"""API routes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from carina import __version__
from carina.api.schemas import (
    AskRequest,
    AskResponse,
    BSARequest,
    CarboplatinRequest,
    FeedbackRequest,
    ScreenRequest,
    SearchRequest,
    StageRequest,
    TherapyRequest,
    TrialRequest,
    UnderstandRequest,
)
from carina.api.security import rate_limit, require_admin, require_api_key
from carina.clinical import dosing, safety_screen, staging, therapy, tool_router, trials
from carina.clinical.understanding import understand
from carina.container import Container, get_container
from carina.domain import PatientContext
from carina.guardrails import emergency, pii, scope
from carina.knowledge import manifest as knowledge_manifest
from carina.observability import metrics

router = APIRouter()


@router.get("/health", tags=["operations"])
def health(container: Container = Depends(get_container)) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "index": {"chunks": len(container.index), "documents": len(container.index.documents), "origin": container.index_origin},
        "providers": container.router.status(),
        "cache": container.cache.backend,
    }


@router.get("/ready", tags=["operations"])
def ready(container: Container = Depends(get_container)) -> dict[str, Any]:
    if len(container.index) == 0:
        raise HTTPException(503, "Knowledge index is empty")
    return {"ready": True, "chunks": len(container.index)}


@router.post("/v1/ask", response_model=AskResponse, tags=["assistant"], dependencies=[Depends(rate_limit)])
async def ask(body: AskRequest, container: Container = Depends(get_container)) -> dict[str, Any]:
    result = await container.pipeline.ask(body.question, body.patient_context, body.provider, body.history_in_scope)
    return result.as_dict()


@router.post("/v1/ask/stream", tags=["assistant"], dependencies=[Depends(rate_limit)])
async def ask_stream(body: AskRequest, container: Container = Depends(get_container)) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        async for event in container.pipeline.stream(body.question, body.patient_context, body.provider, body.history_in_scope):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/v1/understand", tags=["assistant"], dependencies=[Depends(rate_limit)])
def understand_question(body: UnderstandRequest, container: Container = Depends(get_container)) -> dict[str, Any]:
    redacted = pii.redact(body.question)
    qu = understand(redacted.text)
    ctx = qu.to_patient_context(body.patient_context)
    decision = scope.check_scope(redacted.text, qu)
    cards = tool_router.route(qu, ctx, container.index.trials) if decision.in_scope else []
    return {
        "redacted_question": redacted.text,
        "redactions": redacted.counts,
        "understanding": qu.as_dict(),
        "patient_context": ctx.model_dump(exclude_none=True),
        "in_scope": decision.in_scope,
        "emergencies": [a.as_dict() for a in emergency.triage(redacted.text)],
        "tools": [c.as_dict() for c in cards],
    }


@router.post("/v1/search", tags=["evidence"], dependencies=[Depends(rate_limit)])
def search(body: SearchRequest, container: Container = Depends(get_container)) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if body.sources:
        filters["source"] = body.sources
    if body.min_evidence_grade is not None:
        filters["min_evidence_grade"] = body.min_evidence_grade
    if body.jurisdiction:
        filters["jurisdiction"] = body.jurisdiction
    query = pii.redact(body.query).text
    qu = understand(query)
    result = container.retriever.retrieve(qu.retrieval_query(), biomarkers=qu.biomarkers, filters=filters or None, top_k=body.top_k)
    return result.as_dict()


@router.post("/v1/tools/stage", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def stage_tool(body: StageRequest) -> dict[str, Any]:
    try:
        t = body.t
        if body.size_mm is not None:
            t = staging.t_from_size(
                body.size_mm,
                invasive_mm=body.invasive_mm,
                main_bronchus=body.main_bronchus,
                visceral_pleura=body.visceral_pleura,
                atelectasis_to_hilum=body.atelectasis_to_hilum,
                chest_wall_or_pericardium=body.chest_wall_or_pericardium,
                separate_nodule_same_lobe=body.separate_nodule_same_lobe,
                mediastinum_or_great_vessels=body.mediastinum_or_great_vessels,
                separate_nodule_other_ipsilateral_lobe=body.separate_nodule_other_ipsilateral_lobe,
            )
        if body.tnm:
            result = staging.stage_from_text(body.tnm, body.edition)
            if result is None:
                raise staging.StagingError("No TNM combination found in the text")
        else:
            if not t or not body.n:
                raise staging.StagingError("Provide t and n, a tumour size, or a tnm string")
            result = staging.stage(t, body.n, body.m, body.edition)
    except staging.StagingError as exc:
        raise HTTPException(422, str(exc)) from exc
    metrics.TOOL_CALLS.labels("staging", "ok").inc()
    return result.as_dict()


@router.post("/v1/tools/therapy", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def therapy_tool(body: TherapyRequest) -> dict[str, Any]:
    metrics.TOOL_CALLS.labels("therapy_options", "ok").inc()
    return therapy.match_therapies(body.patient_context, include_not_recommended=body.include_not_recommended).as_dict()


@router.post("/v1/tools/trials", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def trials_tool(body: TrialRequest, container: Container = Depends(get_container)) -> dict[str, Any]:
    metrics.TOOL_CALLS.labels("trial_matching", "ok").inc()
    return trials.match_trials(body.patient_context, container.index.trials(), country=body.country, open_only=body.open_only, limit=body.limit)


@router.post("/v1/tools/carboplatin", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def carboplatin_tool(body: CarboplatinRequest) -> dict[str, Any]:
    try:
        if body.gfr_ml_min is not None:
            steps = [dosing.carboplatin_calvert(body.target_auc, body.gfr_ml_min, gfr_source=body.gfr_source, cap_gfr=body.cap_gfr)]
        elif None not in (body.age, body.weight_kg, body.serum_creatinine_umol_l, body.sex):
            steps = dosing.carboplatin_from_patient(body.target_auc, body.age, body.weight_kg, body.serum_creatinine_umol_l, body.sex)  # type: ignore[arg-type]
        else:
            raise dosing.DosingError("Provide gfr_ml_min, or age, weight_kg, serum_creatinine_umol_l and sex")
    except dosing.DosingError as exc:
        raise HTTPException(422, str(exc)) from exc
    metrics.TOOL_CALLS.labels("carboplatin_calvert", "ok").inc()
    return {"steps": [step.as_dict() for step in steps]}


@router.post("/v1/tools/bsa", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def bsa_tool(body: BSARequest) -> dict[str, Any]:
    try:
        return dosing.body_surface_area(body.height_cm, body.weight_kg, body.method).as_dict()
    except dosing.DosingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/tools/screen", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def screen_tool(body: ScreenRequest) -> dict[str, Any]:
    metrics.TOOL_CALLS.labels("safety_screen", "ok").inc()
    return safety_screen.screen(body.planned, body.patient_context).as_dict()


@router.get("/v1/tools/performance", tags=["clinical tools"], dependencies=[Depends(require_api_key)])
def performance_tool(ecog: int | None = None, karnofsky: int | None = None) -> dict[str, Any]:
    try:
        return dosing.performance_status_mapping(ecog=ecog, karnofsky=karnofsky)
    except dosing.DosingError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/feedback", tags=["governance"], dependencies=[Depends(rate_limit)])
def feedback(body: FeedbackRequest, container: Container = Depends(get_container)) -> dict[str, Any]:
    metrics.FEEDBACK.labels(body.rating).inc()
    record = container.audit.feedback(body.request_id, body.rating, list(body.reasons), body.comment)
    return {"stored": True, "request_id": record["request_id"]}


@router.get("/v1/knowledge", tags=["governance"], dependencies=[Depends(require_api_key)])
def knowledge(container: Container = Depends(get_container)) -> dict[str, Any]:
    return {"index": container.index.manifest, "rule_sets": knowledge_manifest()}


@router.get("/v1/audit/summary", tags=["governance"], dependencies=[Depends(require_admin)])
def audit_summary(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.audit.summary()


def empty_context() -> PatientContext:
    return PatientContext()
