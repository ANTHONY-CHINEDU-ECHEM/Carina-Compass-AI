"""Request and response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from carina.domain import PatientContext
from carina.guardrails.pii import redact


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    patient_context: PatientContext | None = None
    provider: Literal["anthropic", "openai", "ollama", "extractive"] | None = None
    history_in_scope: bool = Field(default=False, description="True when earlier turns of this consultation were in scope")


class AskResponse(BaseModel):
    request_id: str
    answer: str
    status: str
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
    cached: bool


class UnderstandRequest(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    patient_context: PatientContext | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)
    sources: list[str] | None = None
    min_evidence_grade: int | None = Field(default=None, ge=0, le=7)
    jurisdiction: str | None = None


class StageRequest(BaseModel):
    t: str | None = None
    n: str | None = None
    m: str = "M0"
    tnm: str | None = Field(default=None, description="Free text such as 'cT2a N2b M0'")
    edition: Literal[8, 9] = 9
    size_mm: float | None = Field(default=None, gt=0, le=300)
    invasive_mm: float | None = Field(default=None, gt=0, le=300)
    main_bronchus: bool = False
    visceral_pleura: bool = False
    atelectasis_to_hilum: bool = False
    chest_wall_or_pericardium: bool = False
    separate_nodule_same_lobe: bool = False
    mediastinum_or_great_vessels: bool = False
    separate_nodule_other_ipsilateral_lobe: bool = False


class TherapyRequest(BaseModel):
    patient_context: PatientContext
    include_not_recommended: bool = True


class TrialRequest(BaseModel):
    patient_context: PatientContext
    country: str = "United Kingdom"
    open_only: bool = True
    limit: int = Field(default=10, ge=1, le=50)


class CarboplatinRequest(BaseModel):
    target_auc: float = Field(ge=1, le=7)
    gfr_ml_min: float | None = Field(default=None, gt=0, le=250)
    gfr_source: Literal["measured", "estimated"] = "estimated"
    age: int | None = Field(default=None, ge=18, le=110)
    weight_kg: float | None = Field(default=None, gt=20, lt=300)
    serum_creatinine_umol_l: float | None = Field(default=None, gt=10, lt=2000)
    sex: Literal["male", "female"] | None = None
    cap_gfr: bool = True


class BSARequest(BaseModel):
    height_cm: float = Field(gt=100, lt=250)
    weight_kg: float = Field(gt=20, lt=300)
    method: Literal["mosteller", "dubois"] = "mosteller"


class ScreenRequest(BaseModel):
    planned: list[str] = Field(min_length=1, max_length=12)
    patient_context: PatientContext = Field(default_factory=PatientContext)


class FeedbackRequest(BaseModel):
    request_id: str = Field(min_length=6, max_length=64)
    rating: Literal["helpful", "not_helpful", "unsafe"]
    reasons: list[Literal["incorrect", "outdated", "missing_source", "unsafe_dose", "not_uk", "too_long", "other"]] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _redact(cls, value: str | None) -> str | None:
        return redact(value).text if value else value
