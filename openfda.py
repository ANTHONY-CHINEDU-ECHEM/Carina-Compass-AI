"""openFDA structured product labels for thoracic oncology medicines.

Only safety and pharmacology sections are indexed. Dosage sections are
deliberately skipped: they describe US licensing and must never be retrieved
as a UK dose. Labels are tagged US jurisdiction and ranked below UK guidance.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

import httpx

from carina.domain import Document, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.grader import grade
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)

API = "https://api.fda.gov/drug/label.json"
SECTIONS = [
    ("boxed_warning", "Boxed warning"),
    ("indications_and_usage", "Indications and usage"),
    ("contraindications", "Contraindications"),
    ("warnings_and_cautions", "Warnings and precautions"),
    ("drug_interactions", "Drug interactions"),
    ("use_in_specific_populations", "Use in specific populations"),
    ("adverse_reactions", "Adverse reactions"),
    ("mechanism_of_action", "Mechanism of action"),
]


class OpenFDASource(Source):
    name = "openfda"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=3.0))
        self.api_key = os.environ.get("OPENFDA_API_KEY")

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        produced = 0
        for drug in self.config.get("drugs", []):
            params = {"search": f'openfda.generic_name:"{drug}"', "limit": "1"}
            if self.api_key:
                params["api_key"] = self.api_key
            try:
                data = self.client.get_json(API, params=params)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    log.info("no label", extra={"drug": drug})
                    continue
                raise
            for label in data.get("results", []):
                doc = parse_label(label, drug)
                if doc:
                    yield doc
                    produced += 1
                    if limit and produced >= limit:
                        return


def parse_label(label: dict, drug: str) -> Document | None:  # type: ignore[type-arg]
    sections = []
    for key, heading in SECTIONS:
        values = label.get(key)
        if not values:
            continue
        text = clean_text(" ".join(values))
        if key == "adverse_reactions":
            text = " ".join(text.split()[:900])
        sections.append((heading, text))
    if not sections:
        return None
    openfda = label.get("openfda", {})
    brand = ", ".join(openfda.get("brand_name", [])[:2])
    set_id = label.get("set_id") or label.get("id")
    effective = str(label.get("effective_time", ""))
    title = f"{drug.title()} US prescribing information" + (f" ({brand})" if brand else "")
    return Document(
        doc_id=f"openfda:{set_id}",
        source=SourceType.DRUG_LABEL,
        title=title,
        url=f"https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={set_id}",
        text="\n\n".join(body for _, body in sections),
        sections=sections,
        year=int(effective[:4]) if effective[:4].isdigit() else None,
        jurisdiction=Jurisdiction.US,
        licence_key="public_domain_us",
        evidence_grade=grade(SourceType.DRUG_LABEL),
        identifiers={"setid": str(set_id), "drug": drug},
        metadata={"brand": brand, "note": "US label; dosage sections are not indexed", **tag_text(title)},
    )
