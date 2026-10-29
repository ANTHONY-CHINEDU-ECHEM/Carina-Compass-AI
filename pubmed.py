"""PubMed through NCBI Entrez E-utilities.

Each query family is searched with the history server (usehistory=y) and
fetched in batches of 200 as XML. A priority pass harvests systematic reviews,
meta analyses, randomised trials and practice guidelines first, so a capped
run still indexes the strongest evidence. Only the bibliographic record and
the abstract are stored.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterator

from carina.domain import Document, Jurisdiction, SourceType
from ingestion.processing.cleaner import clean_text, strip_structured_abstract_labels
from ingestion.processing.grader import grade
from ingestion.processing.tagger import tag_text
from ingestion.sources.base import HttpClient, Source

log = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PRIORITY_FILTER = "(systematic review[pt] OR meta-analysis[pt] OR randomized controlled trial[pt] OR clinical trial, phase iii[pt] OR practice guideline[pt])"
UK_AFFILIATION = ("united kingdom", " uk", "england", "scotland", "wales", "northern ireland", "nhs")


class PubMedSource(Source):
    name = "pubmed"

    def __init__(self, config: dict, client: HttpClient | None = None) -> None:  # type: ignore[type-arg]
        api_key = os.environ.get("NCBI_API_KEY")
        rate = 9.0 if api_key else 2.8
        super().__init__(config, client or HttpClient(rate_per_s=rate))
        self.api_key = api_key
        self.batch = int(config.get("batch_size", 200))

    def _params(self, **extra: str) -> dict[str, str]:
        params = {"db": "pubmed", "tool": "carina_compass", **extra}
        if self.api_key:
            params["api_key"] = self.api_key
        email = os.environ.get("NCBI_EMAIL")
        if email:
            params["email"] = email
        return params

    def _search(self, term: str) -> tuple[int, str, str]:
        data = self.client.get_json(
            f"{EUTILS}/esearch.fcgi",
            params=self._params(term=term, usehistory="y", retmode="json", retmax="0"),
        )
        result = data["esearchresult"]
        return int(result["count"]), result["webenv"], result["querykey"]

    def _fetch(self, webenv: str, query_key: str, start: int) -> list[ET.Element]:
        text = self.client.get_text(
            f"{EUTILS}/efetch.fcgi",
            params=self._params(query_key=query_key, WebEnv=webenv, retstart=str(start), retmax=str(self.batch), retmode="xml"),
        )
        root = ET.fromstring(text)
        return root.findall(".//PubmedArticle")

    def harvest(self, limit: int | None = None) -> Iterator[Document]:
        seen: set[str] = set()
        produced = 0
        families = self.config.get("query_families", {})
        date_filter = self.config.get("date_filter", "")
        passes = [("priority", f" AND {PRIORITY_FILTER}"), ("all", "")]
        for pass_name, extra in passes:
            for family, query in families.items():
                term = f"({query}){extra}{(' AND ' + date_filter) if date_filter else ''}"
                count, webenv, key = self._search(term)
                cap = int(self.config.get("max_per_family", 20000))
                log.info("pubmed family", extra={"family": family, "pass": pass_name, "count": count})
                for start in range(0, min(count, cap), self.batch):
                    for article in self._fetch(webenv, key, start):
                        doc = parse_article(article, family)
                        if doc is None or doc.doc_id in seen:
                            continue
                        seen.add(doc.doc_id)
                        yield doc
                        produced += 1
                        if limit and produced >= limit:
                            return


def _text(node: ET.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_article(article: ET.Element, family: str = "") -> Document | None:
    citation = article.find("MedlineCitation")
    if citation is None:
        return None
    pmid = _text(citation.find("PMID"))
    art = citation.find("Article")
    if not pmid or art is None:
        return None
    title = clean_text(_text(art.find("ArticleTitle")))
    sections: list[tuple[str | None, str]] = []
    for node in art.findall("Abstract/AbstractText"):
        label = node.get("Label")
        body = clean_text(_text(node))
        if body:
            sections.append((label.title() if label else "Abstract", body))
    if not sections:
        return None
    abstract = strip_structured_abstract_labels(" ".join(body for _, body in sections))
    year_text = _text(art.find("Journal/JournalIssue/PubDate/Year")) or _text(art.find("Journal/JournalIssue/PubDate/MedlineDate"))[:4]
    year = int(year_text) if year_text[:4].isdigit() else None
    journal = _text(art.find("Journal/ISOAbbreviation")) or _text(art.find("Journal/Title"))
    pub_types = [_text(pt) for pt in art.findall("PublicationTypeList/PublicationType")]
    mesh = [_text(m.find("DescriptorName")) for m in citation.findall("MeshHeadingList/MeshHeading")]
    doi = ""
    for aid in article.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi":
            doi = _text(aid)
    affiliations = " ".join(_text(a) for a in art.findall(".//AffiliationInfo/Affiliation")).lower()
    jurisdiction = Jurisdiction.UK if any(k in affiliations for k in UK_AFFILIATION) else Jurisdiction.INTERNATIONAL
    tags = tag_text(f"{title} {abstract}")
    identifiers = {"pmid": pmid}
    if doi:
        identifiers["doi"] = doi
    return Document(
        doc_id=f"pubmed:{pmid}",
        source=SourceType.PUBMED,
        title=title,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        text=abstract,
        sections=sections,
        year=year,
        jurisdiction=jurisdiction,
        licence_key="abstract_fair_dealing",
        evidence_grade=grade(SourceType.PUBMED, pub_types, title=title),
        identifiers=identifiers,
        metadata={"journal": journal, "publication_types": pub_types, "mesh": mesh[:25], "family": family, **tags},
    )
