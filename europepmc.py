"""Europe PMC open access full text, restricted to CC BY and CC0 licences.

Search uses cursor paging (cursorMark) with resultType=core so the licence is
known before any full text is downloaded. Full text is fetched as JATS XML and
split into its sections, which become chunk boundaries.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from carina.domain import Document, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text
from ingestion.processing.grader import grade
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)

REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ALLOWED_LICENCES = {"cc by": "cc_by", "cc0": "cc0", "cc-by": "cc_by"}
SKIP_SECTIONS = ("reference", "acknowledg", "funding", "conflict", "competing", "author contribution", "supplementary", "data availability")


class EuropePMCSource(Source):
    name = "europe_pmc"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        super().__init__(config, client or HttpClient(rate_per_s=float(config.get("rate_per_s", 5))))

    def _search_pages(self, query: str) -> Iterator[dict]:  # type: ignore[type-arg]
        cursor = "*"
        while True:
            data = self.client.get_json(
                f"{REST}/search",
                params={"query": query, "format": "json", "resultType": "core", "pageSize": "1000", "cursorMark": cursor},
            )
            results = data.get("resultList", {}).get("result", [])
            yield from results
            next_cursor = data.get("nextCursorMark")
            if not results or not next_cursor or next_cursor == cursor:
                return
            cursor = next_cursor

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        produced = 0
        for query in self.config.get("queries", []):
            full_query = f'({query}) AND OPEN_ACCESS:y AND (LICENSE:"cc by" OR LICENSE:"cc0") AND SRC:MED'
            for record in self._search_pages(full_query):
                licence = ALLOWED_LICENCES.get(str(record.get("license", "")).lower())
                pmcid = record.get("pmcid")
                if not licence or not pmcid:
                    continue
                try:
                    xml = self.client.get_text(f"{REST}/{pmcid}/fullTextXML")
                except Exception as exc:  # noqa: BLE001 - a missing full text must not stop the harvest
                    log.info("no full text", extra={"pmcid": pmcid, "error": str(exc)[:120]})
                    continue
                doc = parse_full_text(record, xml, licence)
                if doc is None:
                    continue
                yield doc
                produced += 1
                if limit and produced >= limit:
                    return


def parse_full_text(record: dict, xml: str, licence_key: str) -> Document | None:  # type: ignore[type-arg]
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    sections: list[tuple[str | None, str]] = []
    abstract = clean_text(" ".join("".join(p.itertext()) for p in root.findall(".//abstract//p")))
    if abstract:
        sections.append(("Abstract", abstract))
    for sec in root.findall(".//body/sec"):
        title_node = sec.find("title")
        title = clean_text("".join(title_node.itertext())) if title_node is not None else None
        if title and any(skip in title.lower() for skip in SKIP_SECTIONS):
            continue
        body = clean_text(" ".join("".join(p.itertext()) for p in sec.findall(".//p")))
        if len(body.split()) > 30:
            sections.append((title, body))
    if not sections:
        return None
    title = clean_text(record.get("title", ""))
    text = "\n\n".join(body for _, body in sections)
    pub_types = record.get("pubTypeList", {}).get("pubType", [])
    year = int(record["pubYear"]) if str(record.get("pubYear", "")).isdigit() else None
    affiliation = str(record.get("affiliation", "")).lower()
    identifiers = {"pmcid": record["pmcid"]}
    if record.get("pmid"):
        identifiers["pmid"] = str(record["pmid"])
    if record.get("doi"):
        identifiers["doi"] = record["doi"]
    return Document(
        doc_id=f"europepmc:{record['pmcid']}",
        source=SourceType.EUROPE_PMC,
        title=title,
        url=f"https://europepmc.org/article/PMC/{record['pmcid']}",
        text=text,
        sections=sections,
        year=year,
        jurisdiction=Jurisdiction.UK if "united kingdom" in affiliation or " uk" in affiliation else Jurisdiction.INTERNATIONAL,
        licence_key=licence_key,
        evidence_grade=grade(SourceType.EUROPE_PMC, pub_types, title=title),
        identifiers=identifiers,
        metadata={"journal": record.get("journalInfo", {}).get("journal", {}).get("title"), "publication_types": pub_types, **tag_text(f"{title} {abstract}")},
    )
