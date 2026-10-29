"""The verified seed snapshot.

The seed lets the service start, the tests run and the evaluation gate pass
before the full harvest has been run, with no network access. It is a small
slice of the real knowledge base, not invented content:

  nice.jsonl             NG122 recommendations by section, 46 NICE technology appraisals
                         (titles and dates from the NICE lung cancer listing) and two
                         superseded documents kept for provenance
  landmark_trials.jsonl  eight pivotal trials with PMIDs confirmed against PubMed
  trial_registry.jsonl   fifteen ClinicalTrials.gov records with confirmed NCT identifiers
  staging.jsonl          the 8th and 9th edition TNM stage groups
  emergencies.jsonl      NICE CG151 (neutropenic sepsis) and NG234 (spinal cord compression)

Every record is a summary written in our own words, carries the URL of its
authoritative source and a `verified` note saying how it was checked.
"""

from __future__ import annotations

import json
from pathlib import Path

from carina.domain import Document, EvidenceGrade, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.grader import grade
from ingestion.processing.tagger import tag_text


def _record_to_document(record: dict) -> Document:  # type: ignore[type-arg]
    source = SourceType(record["source"])
    sections = [(heading, clean_text(text)) for heading, text in record["sections"]]
    text = "\n\n".join(body for _, body in sections)
    metadata = dict(record.get("metadata", {}))
    tags = tag_text(f"{record['title']} {text}")
    for key, values in tags.items():
        existing = metadata.get(key, [])
        metadata[key] = sorted(set(existing) | set(values)) if isinstance(existing, list) else values
    metadata["verified"] = record.get("verified")
    evidence = grade(source, metadata.get("publication_types"), title=record["title"])
    if source == SourceType.CLINICAL_TRIAL:
        evidence = EvidenceGrade.EXPERT_OPINION
    return Document(
        doc_id=record["doc_id"],
        source=source,
        title=record["title"],
        url=record["url"],
        text=text,
        sections=sections,
        year=record.get("year"),
        jurisdiction=Jurisdiction(record.get("jurisdiction", "International")),
        licence_key=record.get("licence_key", "summary_own_words"),
        evidence_grade=evidence,
        identifiers={k: str(v) for k, v in record.get("identifiers", {}).items() if v},
        metadata=metadata,
        superseded_by=record.get("superseded_by"),
    )


def load_seed_documents(seed_dir: Path) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(seed_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    documents.append(_record_to_document(json.loads(line)))
    return documents
