"""Core domain model shared by ingestion, retrieval, generation and the API.

Every document and chunk carries its provenance: where it came from, under
which licence, how strong the evidence is, which jurisdiction it describes and
whether a newer edition has replaced it. Nothing downstream is allowed to lose
these fields, because the clinician needs them to judge an answer.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    """The kind of publication a document came from."""

    NICE_GUIDELINE = "nice_guideline"
    NICE_APPRAISAL = "nice_appraisal"
    PDQ = "nci_pdq"
    PUBMED = "pubmed"
    EUROPE_PMC = "europe_pmc"
    CLINICAL_TRIAL = "clinical_trial"
    CIVIC = "civic"
    DRUG_LABEL = "drug_label"
    PATIENT_INFO = "patient_info"
    STAGING_REFERENCE = "staging_reference"


class EvidenceGrade(IntEnum):
    """Seven step evidence ladder used for ranking and for display.

    UK national guidance sits at the top because it is what a UK multidisciplinary
    team is accountable to. A trial registry entry is graded as expert opinion
    level: it proves a study exists, not that a treatment works.
    """

    UNGRADED = 0
    EXPERT_OPINION = 1
    CASE_REPORT = 2
    OBSERVATIONAL_OR_REGULATORY = 3
    RANDOMISED_TRIAL = 4
    SYSTEMATIC_REVIEW = 5
    INTERNATIONAL_GUIDANCE = 6
    UK_NATIONAL_GUIDANCE = 7

    @property
    def label(self) -> str:
        return _GRADE_LABELS[self]


_GRADE_LABELS = {
    EvidenceGrade.UNGRADED: "Ungraded",
    EvidenceGrade.EXPERT_OPINION: "Expert opinion, narrative review or registry entry",
    EvidenceGrade.CASE_REPORT: "Case report or series",
    EvidenceGrade.OBSERVATIONAL_OR_REGULATORY: "Observational, early phase or regulatory",
    EvidenceGrade.RANDOMISED_TRIAL: "Randomised controlled trial",
    EvidenceGrade.SYSTEMATIC_REVIEW: "Systematic review or meta analysis",
    EvidenceGrade.INTERNATIONAL_GUIDANCE: "International guidance or evidence summary",
    EvidenceGrade.UK_NATIONAL_GUIDANCE: "UK national guidance",
}


class Jurisdiction(str, Enum):
    UK = "UK"
    US = "US"
    EU = "EU"
    INTERNATIONAL = "International"


class Licence(BaseModel):
    """Licence under which a document may be stored and shown."""

    name: str
    url: str | None = None
    redistributable: bool = False
    notes: str | None = None


LICENCES: dict[str, Licence] = {
    "nice": Licence(
        name="NICE content, used under the NICE Syndication licence or as a paraphrased summary",
        url="https://www.nice.org.uk/re-using-our-content/uk-open-content-licence",
        redistributable=False,
        notes="Full text requires a NICE syndication licence; summaries are written in our own words.",
    ),
    "public_domain_us": Licence(
        name="US government work, public domain",
        url="https://www.usa.gov/government-copyright",
        redistributable=True,
    ),
    "cc_by": Licence(name="CC BY 4.0", url="https://creativecommons.org/licenses/by/4.0/", redistributable=True),
    "cc0": Licence(name="CC0 1.0", url="https://creativecommons.org/publicdomain/zero/1.0/", redistributable=True),
    "abstract_fair_dealing": Licence(
        name="Publisher copyright; abstract indexed for retrieval and short quotation",
        redistributable=False,
        notes="Only the bibliographic record and a summary are stored; follow the link for the full article.",
    ),
    "summary_own_words": Licence(
        name="Summary written in our own words with a link to the authoritative source",
        redistributable=True,
    ),
}


class Document(BaseModel):
    """A single source document after harvesting and cleaning."""

    doc_id: str
    source: SourceType
    title: str
    url: str
    text: str
    sections: list[tuple[str | None, str]] = Field(default_factory=list)
    year: int | None = None
    published: date | None = None
    jurisdiction: Jurisdiction = Jurisdiction.INTERNATIONAL
    licence_key: str = "summary_own_words"
    evidence_grade: EvidenceGrade = EvidenceGrade.UNGRADED
    identifiers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    superseded_by: str | None = None

    @field_validator("title", "text")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def licence(self) -> Licence:
        return LICENCES.get(self.licence_key, LICENCES["summary_own_words"])

    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.text}".encode()).hexdigest()[:16]


class Chunk(BaseModel):
    """A retrievable passage. Inherits provenance from its parent document."""

    chunk_id: str
    doc_id: str
    text: str
    section: str | None = None
    position: int = 0
    title: str
    url: str
    source: SourceType
    year: int | None = None
    jurisdiction: Jurisdiction = Jurisdiction.INTERNATIONAL
    evidence_grade: EvidenceGrade = EvidenceGrade.UNGRADED
    licence_key: str = "summary_own_words"
    identifiers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    superseded_by: str | None = None

    @classmethod
    def from_document(cls, doc: Document, text: str, section: str | None, position: int) -> Chunk:
        return cls(
            chunk_id=f"{doc.doc_id}::{position}",
            doc_id=doc.doc_id,
            text=text,
            section=section,
            position=position,
            title=doc.title,
            url=doc.url,
            source=doc.source,
            year=doc.year,
            jurisdiction=doc.jurisdiction,
            evidence_grade=doc.evidence_grade,
            licence_key=doc.licence_key,
            identifiers=doc.identifiers,
            metadata=doc.metadata,
            superseded_by=doc.superseded_by,
        )


class ScoredChunk(BaseModel):
    """A chunk with the scores it collected on its way through retrieval."""

    chunk: Chunk
    dense_score: float = 0.0
    sparse_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float = 0.0
    final_score: float = 0.0
    signals: dict[str, float] = Field(default_factory=dict)
    superseded: bool = False


class PatientContext(BaseModel):
    """De identified clinical context supplied with a question.

    No name, NHS number, date of birth or address is ever accepted here. The
    API rejects free text fields that contain identifiers after redaction.
    """

    histology: str | None = None
    stage_group: str | None = None
    t_category: str | None = None
    n_category: str | None = None
    m_category: str | None = None
    biomarkers: list[str] = Field(default_factory=list)
    pdl1_tps: float | None = Field(default=None, ge=0, le=100)
    performance_status: int | None = Field(default=None, ge=0, le=4)
    age: int | None = Field(default=None, ge=18, le=110)
    sex: str | None = None
    weight_kg: float | None = Field(default=None, gt=20, lt=300)
    height_cm: float | None = Field(default=None, gt=100, lt=250)
    serum_creatinine_umol_l: float | None = Field(default=None, gt=10, lt=2000)
    setting: str | None = None
    line_of_therapy: int | None = Field(default=None, ge=1, le=6)
    prior_treatments: list[str] = Field(default_factory=list)
    current_medicines: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(value not in (None, [], "") for value in self.model_dump().values())
