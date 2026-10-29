"""Section aware chunking.

Chunks never cross a section boundary (a NICE recommendation group, an
abstract's Results, a trial's eligibility criteria), are cut at sentence
boundaries, and overlap by a sentence so a finding is never separated from its
context. A short section is kept whole even if it is under the target size.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from carina.domain import Chunk, Document
from carina.retrieval.hybrid import setting_group
from ingestion.processing.tagger import tag_text

SENTENCE = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9(\[\"'])")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text) if s.strip()]


def _with_chunk_tags(chunk: Chunk, doc: Document) -> Chunk:
    """Tag each chunk from its own text.

    Document level tags describe the whole guideline, which may span adjuvant,
    consolidation and metastatic settings. Chunk level tags let retrieval tell
    an adjuvant recommendation from a first line one inside the same guideline.
    Biomarkers fall back to the document tags when a chunk names none, because
    a trial's Results section rarely repeats the mutation it studied.
    """
    tags = tag_text(f"{chunk.section or ''} {chunk.text}")
    metadata = dict(doc.metadata)
    metadata["biomarkers"] = tags["biomarkers"] or list(doc.metadata.get("biomarkers", []))
    doc_settings = list(doc.metadata.get("settings", []))
    doc_groups = {setting_group(s) for s in doc_settings} - {None}
    metadata["settings"] = tags["settings"] or (doc_settings if len(doc_groups) == 1 else [])
    metadata["histology"] = tags["histology"] or list(doc.metadata.get("histology", []))
    metadata["drugs"] = tags["drugs"] or list(doc.metadata.get("drugs", []))
    return chunk.model_copy(update={"metadata": metadata})


def chunk_document(doc: Document, target_words: int = 180, max_words: int = 260, overlap_sentences: int = 1) -> Iterator[Chunk]:
    for chunk in _chunk_document(doc, target_words, max_words, overlap_sentences):
        yield _with_chunk_tags(chunk, doc)


def _chunk_document(doc: Document, target_words: int = 180, max_words: int = 260, overlap_sentences: int = 1) -> Iterator[Chunk]:
    sections: list[tuple[str | None, str]] = list(doc.sections) or [(None, doc.text)]
    position = 0
    for section_title, section_text in sections:
        sentences = split_sentences(section_text)
        window: list[str] = []
        words = 0
        fresh = 0  # sentences in the window that have not been emitted yet
        for sentence in sentences:
            n = len(sentence.split())
            if window and fresh and words + n > max_words:
                yield Chunk.from_document(doc, " ".join(window), section_title, position)
                position += 1
                window, words, fresh = _carry(window, overlap_sentences)
            window.append(sentence)
            words += n
            fresh += 1
            if words >= target_words:
                yield Chunk.from_document(doc, " ".join(window), section_title, position)
                position += 1
                window, words, fresh = _carry(window, overlap_sentences)
        if fresh:
            yield Chunk.from_document(doc, " ".join(window), section_title, position)
            position += 1


def _carry(window: list[str], overlap: int) -> tuple[list[str], int, int]:
    kept = window[-overlap:] if overlap else []
    return kept, sum(len(s.split()) for s in kept), 0
