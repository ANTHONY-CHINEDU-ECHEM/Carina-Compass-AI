"""ClinicalTrials.gov API version 2.

Studies are paged with pageToken (pageSize up to 1000). Each record becomes a
document whose sections are the brief summary, eligibility criteria, arms and
interventions and primary outcomes, and whose metadata carries the structured
fields the trial matcher filters on: status, phases, age limits, sex,
countries, UK sites and biomarker, histology and setting tags.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

from carina.domain import Document, EvidenceGrade, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)

API = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsSource(Source):
    name = "clinical_trials"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=0.8))

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        produced = 0
        seen: set[str] = set()
        statuses = self.config.get("statuses")
        for condition in self.config.get("conditions", []):
            token: str | None = None
            while True:
                params: dict[str, str] = {"query.cond": condition, "pageSize": "1000", "format": "json"}
                if statuses:
                    params["filter.overallStatus"] = ",".join(statuses)
                if token:
                    params["pageToken"] = token
                data = self.client.get_json(API, params=params)
                for study in data.get("studies", []):
                    doc = parse_study(study)
                    if doc is None or doc.doc_id in seen:
                        continue
                    seen.add(doc.doc_id)
                    yield doc
                    produced += 1
                    if limit and produced >= limit:
                        return
                token = data.get("nextPageToken")
                if not token:
                    break


def _get(data: dict[str, Any], *path: str, default: Any = None) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def parse_study(study: dict[str, Any]) -> Document | None:
    protocol = study.get("protocolSection", {})
    nct = _get(protocol, "identificationModule", "nctId")
    if not nct:
        return None
    title = clean_text(_get(protocol, "identificationModule", "officialTitle") or _get(protocol, "identificationModule", "briefTitle", default=""))
    brief_title = clean_text(_get(protocol, "identificationModule", "briefTitle", default=title))
    summary = clean_text(_get(protocol, "descriptionModule", "briefSummary", default=""))
    eligibility = clean_text(_get(protocol, "eligibilityModule", "eligibilityCriteria", default=""))
    interventions = _get(protocol, "armsInterventionsModule", "interventions", default=[]) or []
    outcomes = _get(protocol, "outcomesModule", "primaryOutcomes", default=[]) or []
    locations = _get(protocol, "contactsLocationsModule", "locations", default=[]) or []
    status = _get(protocol, "statusModule", "overallStatus", default="UNKNOWN")
    phases = _get(protocol, "designModule", "phases", default=[]) or []
    conditions = _get(protocol, "conditionsModule", "conditions", default=[]) or []
    last_update = _get(protocol, "statusModule", "lastUpdatePostDateStruct", "date")
    start = _get(protocol, "statusModule", "startDateStruct", "date")

    intervention_text = "; ".join(
        f"{i.get('type', '').title()}: {i.get('name', '')}" + (f" ({clean_text(i.get('description', ''))[:300]})" if i.get("description") else "")
        for i in interventions
    )
    outcome_text = "; ".join(f"{o.get('measure', '')} ({o.get('timeFrame', '')})" for o in outcomes)
    sections: list[tuple[str | None, str]] = []
    if summary:
        sections.append(("Brief summary", summary))
    if intervention_text:
        sections.append(("Interventions", intervention_text))
    if eligibility:
        sections.append(("Eligibility criteria", eligibility))
    if outcome_text:
        sections.append(("Primary outcomes", outcome_text))
    if not sections:
        return None
    countries = sorted({loc.get("country") for loc in locations if loc.get("country")})
    uk_sites = sorted({f"{loc.get('facility', 'Site')}, {loc.get('city', '')}".strip(", ") for loc in locations if loc.get("country") == "United Kingdom"})
    tags = tag_text(f"{brief_title} {summary} {eligibility[:3000]}")
    year = int(start[:4]) if isinstance(start, str) and start[:4].isdigit() else None
    return Document(
        doc_id=f"nct:{nct}",
        source=SourceType.CLINICAL_TRIAL,
        title=brief_title,
        url=f"https://clinicaltrials.gov/study/{nct}",
        text="\n\n".join(body for _, body in sections),
        sections=sections,
        year=year,
        jurisdiction=Jurisdiction.UK if "United Kingdom" in countries else Jurisdiction.INTERNATIONAL,
        licence_key="public_domain_us",
        evidence_grade=EvidenceGrade.EXPERT_OPINION,
        identifiers={"nct": nct},
        metadata={
            "overall_status": status,
            "status_verified": True,
            "status_checked": date.today().isoformat(),
            "phases": phases,
            "conditions": conditions,
            "interventions": [i.get("name") for i in interventions],
            "minimum_age": _get(protocol, "eligibilityModule", "minimumAge"),
            "maximum_age": _get(protocol, "eligibilityModule", "maximumAge"),
            "sex": _get(protocol, "eligibilityModule", "sex", default="ALL"),
            "countries": countries,
            "uk_sites": uk_sites[:40],
            "last_update": last_update,
            "official_title": title,
            **tags,
        },
    )
