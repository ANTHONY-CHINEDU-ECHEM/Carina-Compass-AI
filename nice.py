"""NICE guidance through the NICE Syndication API.

NICE content may only be stored and redistributed under a NICE syndication
licence. The connector is therefore disabled unless NICE_SYNDICATION_API_KEY is
set. The API base and endpoint template are configurable because they are
issued with the licence; the defaults follow the published syndication pattern
of an API-Key header and a JSON document per guidance product.

Without a licence the index still contains the NICE recommendations through
the seed set, which holds summaries written in our own words with links to
the authoritative pages.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from html.parser import HTMLParser

from carina.domain import Document, EvidenceGrade, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)


class _SectionParser(HTMLParser):
    """Split syndicated HTML into (heading, text) sections at h2 and h3."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[tuple[str | None, list[str]]] = [(None, [])]
        self._in_heading = False
        self._heading: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h2", "h3"):
            self._in_heading = True
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h2", "h3") and self._in_heading:
            self._in_heading = False
            self.sections.append((clean_text(" ".join(self._heading)), []))

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._heading.append(data)
        else:
            self.sections[-1][1].append(data)


def html_sections(html: str) -> list[tuple[str | None, str]]:
    parser = _SectionParser()
    parser.feed(html)
    out = []
    for heading, parts in parser.sections:
        text = clean_text(" ".join(parts))
        if len(text.split()) > 15:
            out.append((heading, text))
    return out


class NiceSource(Source):
    name = "nice"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=1.0))
        self.api_key = os.environ.get("NICE_SYNDICATION_API_KEY")
        self.base = os.environ.get("NICE_API_BASE", config.get("api_base", "https://api.nice.org.uk/services"))
        self.template = config.get("endpoint_template", "{base}/content/guidance/{id}")

    def enabled(self) -> bool:
        if not self.api_key:
            log.warning("NICE connector disabled: set NICE_SYNDICATION_API_KEY to harvest under the syndication licence")
            return False
        return super().enabled()

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        if not self.api_key:
            return
        produced = 0
        headers = {"API-Key": self.api_key, "Accept": "application/vnd.nice.syndication.guidance+json;version=1.0"}
        for product in self.config.get("products", []):
            url = self.template.format(base=self.base, id=product["id"].lower())
            data = self.client.get_json(url, headers=headers)
            doc = parse_product(product, data)
            if doc:
                yield doc
                produced += 1
                if limit and produced >= limit:
                    return


def parse_product(product: dict, data: dict) -> Document | None:  # type: ignore[type-arg]
    html = data.get("content") or data.get("body") or ""
    sections = html_sections(html) if html else []
    if not sections:
        return None
    pid = product["id"].upper()
    source = SourceType.NICE_APPRAISAL if pid.startswith("TA") else SourceType.NICE_GUIDELINE
    year = data.get("lastUpdated", data.get("published", ""))[:4]
    return Document(
        doc_id=f"nice:{pid}",
        source=source,
        title=f"NICE {pid}: {data.get('title', product.get('title', ''))}",
        url=f"https://www.nice.org.uk/guidance/{pid.lower()}",
        text="\n\n".join(body for _, body in sections),
        sections=sections,
        year=int(year) if year.isdigit() else None,
        jurisdiction=Jurisdiction.UK,
        licence_key="nice",
        evidence_grade=EvidenceGrade.UK_NATIONAL_GUIDANCE,
        identifiers={"nice": pid},
        metadata=tag_text(" ".join(body for _, body in sections)[:6000]),
    )
