"""MedlinePlus health topics (NLM web service, public domain).

Plain language explanations help clinicians prepare patient conversations.
They are graded at the bottom of the evidence ladder so they never outrank
guidance or trials in a clinical answer.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator

from carina.domain import Document, EvidenceGrade, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

API = "https://wsearch.nlm.nih.gov/ws/query"


class MedlinePlusSource(Source):
    name = "medlineplus"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=1.0))

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        produced = 0
        for term in self.config.get("terms", []):
            xml = self.client.get_text(API, params={"db": "healthTopics", "term": term, "retmax": "20"})
            root = ET.fromstring(xml)
            for doc_node in root.findall(".//document"):
                url = doc_node.get("url", "")
                fields = {c.get("name"): clean_text("".join(c.itertext())) for c in doc_node.findall("content")}
                title = fields.get("title", "")
                summary = fields.get("FullSummary", "")
                if not url or len(summary.split()) < 30:
                    continue
                yield Document(
                    doc_id=f"medlineplus:{url.rstrip('/').rsplit('/', 1)[-1]}",
                    source=SourceType.PATIENT_INFO,
                    title=f"MedlinePlus: {title}",
                    url=url,
                    text=summary,
                    jurisdiction=Jurisdiction.US,
                    licence_key="public_domain_us",
                    evidence_grade=EvidenceGrade.EXPERT_OPINION,
                    identifiers={"medlineplus": url},
                    metadata=tag_text(summary),
                )
                produced += 1
                if limit and produced >= limit:
                    return
