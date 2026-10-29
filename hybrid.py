"""Hybrid retrieval with clinical priors.

Pipeline
  1. Dense search (top_k_dense) and BM25 search (top_k_sparse) on the expanded query.
  2. Reciprocal rank fusion, k = rrf_k.
  3. Rerank the fused head (top_k_rerank) with the cross encoder or lexical reranker.
  4. Rescore with clinical priors:
       evidence grade on the seven step ladder,
       recency with an exponential half life (research only; guidance is dated by currency),
       a UK jurisdiction bonus,
       a biomarker match bonus when the passage names the same driver as the question,
       a penalty for passages from superseded guidance.
  5. Diversity: no document may fill more than max_chunks_per_doc of the final slots.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from carina.config import Settings
from carina.domain import EvidenceGrade, Jurisdiction, ScoredChunk, SourceType
from carina.retrieval.embedder import Embedder
from carina.retrieval.index import KnowledgeIndex, _index_text
from carina.retrieval.reranker import Reranker
from carina.retrieval.supersession import superseding

GUIDANCE_SOURCES = {SourceType.NICE_GUIDELINE, SourceType.NICE_APPRAISAL, SourceType.PDQ, SourceType.STAGING_REFERENCE}

# Treatment settings grouped by disease phase. A passage about adjuvant therapy is
# the wrong evidence for a first line metastatic question, even when it names the
# same drug and the same mutation.
SETTING_GROUPS = {
    "adjuvant": "early",
    "neoadjuvant": "early",
    "perioperative": "early",
    "consolidation_after_crt": "locally_advanced",
    "unresectable_stage3": "locally_advanced",
    "advanced_first_line": "advanced",
    "advanced_subsequent": "advanced",
    "advanced_any_line": "advanced",
    "limited_stage_sclc": "sclc_limited",
    "extensive_stage_sclc": "sclc_extensive",
    "relapsed_sclc": "sclc_relapsed",
}


def setting_group(setting: str | None) -> str | None:
    return SETTING_GROUPS.get(setting or "")


HISTOLOGY_CONFLICTS = {
    "squamous": {"non_squamous", "adenocarcinoma", "small_cell"},
    "adenocarcinoma": {"squamous", "small_cell"},
    "non_squamous": {"squamous", "small_cell"},
    "large_cell": {"squamous", "small_cell"},
    "nsclc": {"small_cell"},
    "small_cell": {"squamous", "non_squamous", "adenocarcinoma"},
}


def histology_relation(query_histology: str | None, chunk_histology: list[str]) -> tuple[float, float]:
    """Return (match, conflict) for a question histology against a passage's histology tags."""
    if not query_histology or not chunk_histology:
        return 0.0, 0.0
    tags = set(chunk_histology)
    if query_histology in tags or (query_histology in ("adenocarcinoma", "large_cell") and "non_squamous" in tags):
        return 1.0, 0.0
    if query_histology == "small_cell" and "nsclc" in tags and "small_cell" not in tags:
        return 0.0, 1.0
    if tags & HISTOLOGY_CONFLICTS.get(query_histology, set()) and query_histology not in tags:
        return 0.0, 1.0
    return 0.0, 0.0


@dataclass
class RetrievalResult:
    query: str
    results: list[ScoredChunk]
    dense_hits: int
    sparse_hits: int
    fused_hits: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "dense_hits": self.dense_hits,
            "sparse_hits": self.sparse_hits,
            "fused_hits": self.fused_hits,
            "results": [
                {
                    "chunk_id": r.chunk.chunk_id,
                    "title": r.chunk.title,
                    "section": r.chunk.section,
                    "url": r.chunk.url,
                    "source": r.chunk.source.value,
                    "evidence_grade": int(r.chunk.evidence_grade),
                    "year": r.chunk.year,
                    "final_score": round(r.final_score, 4),
                    "signals": {k: round(v, 4) for k, v in r.signals.items()},
                    "superseded": r.superseded,
                    "text": r.chunk.text,
                }
                for r in self.results
            ],
        }


class HybridRetriever:
    def __init__(self, index: KnowledgeIndex, embedder: Embedder, reranker: Reranker, settings: Settings) -> None:
        self.index = index
        self.embedder = embedder
        self.reranker = reranker
        self.settings = settings

    def retrieve(
        self,
        query: str,
        *,
        biomarkers: list[str] | None = None,
        setting: str | None = None,
        histology: str | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        rerank_query: str | None = None,
        expansions: str = "",
        prefer_results: bool = False,
    ) -> RetrievalResult:
        """Retrieve evidence.

        `query` (question plus expansions) drives recall in BM25 and the dense
        index; `rerank_query` (the question itself) drives precision, with the
        expansions given only partial credit by the reranker.
        """
        s = self.settings
        top_k = top_k or s.top_k_final
        if len(self.index) == 0:
            return RetrievalResult(query, [], 0, 0, 0)

        q_vec = self.embedder.embed([query], is_query=True)[0]
        dense = self.index.vectors.search(q_vec, s.top_k_dense, filters)
        sparse = self.index.bm25.search(query, s.top_k_sparse)
        if filters:
            sparse = [(cid, sc) for cid, sc in sparse if _passes_filters(self.index, cid, filters)]

        fused: dict[str, float] = defaultdict(float)
        dense_scores = dict(dense)
        sparse_scores = dict(sparse)
        for rank, (cid, _) in enumerate(dense):
            fused[cid] += 1.0 / (s.rrf_k + rank + 1)
        for rank, (cid, _) in enumerate(sparse):
            fused[cid] += 1.0 / (s.rrf_k + rank + 1)
        head = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[: s.top_k_rerank]
        candidates = [self.index.chunks[cid] for cid, _ in head if cid in self.index.chunks]
        if not candidates:
            return RetrievalResult(query, [], len(dense), len(sparse), 0)

        rerank_scores = self.reranker.score(rerank_query or query, [_index_text(c) for c in candidates], expansions)
        this_year = date.today().year
        wanted_biomarkers = set(biomarkers or [])
        wanted_group = setting_group(setting)
        scored: list[ScoredChunk] = []
        for chunk, rerank in zip(candidates, rerank_scores, strict=True):
            evidence = int(chunk.evidence_grade) / int(EvidenceGrade.UK_NATIONAL_GUIDANCE)
            if chunk.source in GUIDANCE_SOURCES or not chunk.year:
                recency = 1.0
            else:
                age = max(0, this_year - chunk.year)
                recency = math.pow(0.5, age / s.recency_half_life_years)
            uk = 1.0 if chunk.jurisdiction == Jurisdiction.UK else 0.0
            chunk_markers = set(chunk.metadata.get("biomarkers", []))
            marker = 1.0 if wanted_biomarkers and wanted_biomarkers & chunk_markers else 0.0
            marker_conflict = 1.0 if wanted_biomarkers and chunk_markers and not (wanted_biomarkers & chunk_markers) else 0.0
            hist_match, hist_conflict = histology_relation(histology, chunk.metadata.get("histology", []))
            chunk_groups = {setting_group(x) for x in chunk.metadata.get("settings", [])} - {None}
            setting_match = 1.0 if wanted_group and wanted_group in chunk_groups else 0.0
            setting_conflict = 1.0 if wanted_group and chunk_groups and wanted_group not in chunk_groups else 0.0
            hist_match, hist_conflict = histology_relation(histology, chunk.metadata.get("histology", []))
            # Priors scale relevance rather than add to it, so an irrelevant passage from
            # strong guidance cannot outrank a relevant one on provenance alone.
            boost = (
                1.0
                + s.evidence_weight * evidence
                + s.recency_weight * recency
                + s.uk_bonus * uk
                + s.biomarker_bonus * marker
                - s.biomarker_bonus * 1.5 * marker_conflict
                + s.setting_bonus * setting_match
                - s.setting_bonus * setting_conflict
                + s.histology_bonus * hist_match
                - s.histology_bonus * 1.5 * hist_conflict
            )
            if prefer_results and (chunk.section or "").lower() in ("results", "findings", "conclusion", "conclusions"):
                boost += 0.4
            final = rerank * max(0.2, boost)
            replaced = superseding(chunk)
            if replaced:
                final *= s.superseded_penalty
            scored.append(
                ScoredChunk(
                    chunk=chunk,
                    dense_score=dense_scores.get(chunk.chunk_id, 0.0),
                    sparse_score=sparse_scores.get(chunk.chunk_id, 0.0),
                    fused_score=fused[chunk.chunk_id],
                    rerank_score=rerank,
                    final_score=final,
                    superseded=bool(replaced),
                    signals={
                        "rerank": rerank,
                        "evidence": evidence,
                        "recency": recency,
                        "uk": uk,
                        "biomarker_match": marker,
                        "biomarker_conflict": marker_conflict,
                        "setting_match": setting_match,
                        "setting_conflict": setting_conflict,
                        "histology_match": hist_match,
                        "histology_conflict": hist_conflict,
                    },
                )
            )

        scored.sort(key=lambda sc: sc.final_score, reverse=True)
        per_doc: dict[str, int] = defaultdict(int)
        selected: list[ScoredChunk] = []
        for item in scored:
            if per_doc[item.chunk.doc_id] >= s.max_chunks_per_doc:
                continue
            per_doc[item.chunk.doc_id] += 1
            selected.append(item)
            if len(selected) >= top_k:
                break
        return RetrievalResult(query, selected, len(dense), len(sparse), len(fused))


def _passes_filters(index: KnowledgeIndex, chunk_id: str, filters: dict[str, Any]) -> bool:
    chunk = index.chunks.get(chunk_id)
    if chunk is None:
        return False
    for key, wanted in filters.items():
        if key == "min_evidence_grade":
            if int(chunk.evidence_grade) < wanted:
                return False
            continue
        value = {"source": chunk.source.value, "jurisdiction": chunk.jurisdiction.value, "year": chunk.year}.get(key)
        if isinstance(wanted, list):
            if value not in wanted:
                return False
        elif value != wanted:
            return False
    return True
