"""NCI PDQ health professional cancer information summaries (public domain).

The PDQ treatment summaries for non small cell and small cell lung cancer are
evidence reviewed by NCI editorial boards and are US government works. Pages
are fetched politely after a robots.txt check and split at their h2 and h3
headings; reference lists are dropped.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

from carina.domain import Document, EvidenceGrade, Jurisdiction, SourceType
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source
from ingestion.sources.nice import html_sections

log = logging.getLogger(__name__)


class PDQSource(Source):
    name = "nci_pdq"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=0.5))

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        produced = 0
        for page in self.config.get("pages", []):
            try:
                html = self.client.get_text(page["url"], check_robots=True)
            except PermissionError as exc:
                log.warning("robots.txt disallows page", extra={"url": page["url"], "error": str(exc)})
                continue
            sections = [(h, t) for h, t in html_sections(html) if not (h or "").lower().startswith(("references", "changes to this summary", "about this pdq"))]
            if not sections:
                continue
            yield Document(
                doc_id=f"pdq:{page['id']}",
                source=SourceType.PDQ,
                title=page["title"],
                url=page["url"],
                text="\n\n".join(t for _, t in sections),
                sections=sections,
                year=date.today().year,
                jurisdiction=Jurisdiction.US,
                licence_key="public_domain_us",
                evidence_grade=EvidenceGrade.INTERNATIONAL_GUIDANCE,
                identifiers={"pdq": page["id"]},
                metadata=tag_text(page["title"]),
            )
            produced += 1
            if limit and produced >= limit:
                return
