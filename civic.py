"""CIViC clinical interpretations of variants in cancer (CC0).

The nightly evidence summary TSV is downloaded and filtered to lung cancer
diseases and predictive, prognostic or diagnostic evidence that has been
accepted by CIViC editors. Column names have changed between CIViC releases,
so columns are resolved by a list of aliases rather than by position.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator

from carina.domain import Document, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.grader import grade
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)

DEFAULT_URL = "https://civicdb.org/downloads/nightly/nightly-ClinicalEvidenceSummaries.tsv"

COLUMN_ALIASES = {
    "evidence_id": ["evidence_id", "eid"],
    "profile": ["molecular_profile", "variant", "molecular_profile_name"],
    "gene": ["gene", "feature_name"],
    "disease": ["disease"],
    "therapies": ["therapies", "drugs"],
    "evidence_type": ["evidence_type"],
    "direction": ["evidence_direction"],
    "significance": ["significance", "clinical_significance"],
    "level": ["evidence_level"],
    "statement": ["evidence_statement", "description"],
    "citation_id": ["citation_id", "pubmed_id"],
    "source_type": ["source_type"],
    "status": ["evidence_status", "status"],
    "rating": ["rating", "evidence_rating"],
}


def _resolve(header: list[str]) -> dict[str, str]:
    lowered = {h.lower(): h for h in header}
    resolved = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                resolved[key] = lowered[alias]
                break
    return resolved


class CivicSource(Source):
    name = "civic"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=1.0))

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        text = self.client.get_text(self.config.get("url", DEFAULT_URL))
        yield from parse_tsv(text, self.config.get("diseases", []), limit)


def parse_tsv(text: str, diseases: list[str], limit: int | None = None) -> Iterator[Document]:
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    cols = _resolve(list(reader.fieldnames or []))
    wanted = {d.lower() for d in diseases}
    produced = 0
    for row in reader:

        def col(key: str, row: dict[str, str] = row) -> str:
            return (row.get(cols.get(key, ""), "") or "").strip()

        disease = col("disease")
        if wanted and disease.lower() not in wanted:
            continue
        if col("status") and col("status").lower() not in ("accepted", ""):
            continue
        if col("evidence_type").lower() not in ("predictive", "prognostic", "diagnostic"):
            continue
        statement = clean_text(col("statement"))
        if len(statement.split()) < 8:
            continue
        eid = col("evidence_id")
        profile = col("profile") or col("gene")
        therapies = col("therapies")
        level = col("level")
        title = f"CIViC EID{eid}: {profile} in {disease}" + (f" and {therapies}" if therapies else "")
        header = (
            f"{col('evidence_type').title()} evidence (level {level}, {col('direction').lower()} "
            f"{col('significance').lower()}) for {profile} in {disease}" + (f" with {therapies}" if therapies else "") + "."
        )
        identifiers = {"civic_eid": eid}
        if col("source_type").lower() == "pubmed" and col("citation_id"):
            identifiers["pmid"] = col("citation_id")
        yield Document(
            doc_id=f"civic:{eid}",
            source=SourceType.CIVIC,
            title=title,
            url=f"https://civicdb.org/evidence/{eid}/summary",
            text=f"{header} {statement}",
            year=None,
            jurisdiction=Jurisdiction.INTERNATIONAL,
            licence_key="cc0",
            evidence_grade=grade(SourceType.CIVIC, civic_level=level),
            identifiers=identifiers,
            metadata={
                "civic_level": level,
                "evidence_type": col("evidence_type"),
                "therapies": therapies,
                "molecular_profile": profile,
                **tag_text(f"{profile} {statement}"),
            },
        )
        produced += 1
        if limit and produced >= limit:
            return
