"""Near duplicate detection with 64 bit SimHash.

The same trial result is often indexed several times: the PubMed abstract,
the Europe PMC record of the same article and a conference version. Records
whose SimHash fingerprints differ by at most `max_distance` bits are
collapsed, keeping the version with the higher evidence grade, then the
richer text, then the newer year.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from carina.domain import Document

WORD = re.compile(r"[a-z0-9]+")


def simhash(text: str, shingle: int = 3) -> int:
    words = WORD.findall(text.lower())
    if len(words) < shingle:
        words = words + [""] * (shingle - len(words))
    vector = [0] * 64
    for i in range(len(words) - shingle + 1):
        token = " ".join(words[i : i + shingle])
        h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "little")
        for bit in range(64):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    return sum(1 << bit for bit in range(64) if vector[bit] > 0)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _better(a: Document, b: Document) -> Document:
    key_a = (int(a.evidence_grade), len(a.text), a.year or 0)
    key_b = (int(b.evidence_grade), len(b.text), b.year or 0)
    return a if key_a >= key_b else b


def deduplicate(documents: Iterable[Document], max_distance: int = 3) -> tuple[list[Document], int]:
    """Return unique documents and the number collapsed.

    Fingerprints are bucketed by four 16 bit bands so comparison stays close
    to linear: two fingerprints within 3 bits must share at least one band.
    """
    kept: list[Document] = []
    prints: list[int] = []
    bands: dict[tuple[int, int], list[int]] = {}
    seen_ids: dict[str, int] = {}
    collapsed = 0
    for doc in documents:
        identity = doc.identifiers.get("pmid") or doc.identifiers.get("doi") or doc.identifiers.get("nct")
        if identity and identity in seen_ids:
            idx = seen_ids[identity]
            kept[idx] = _better(kept[idx], doc)
            collapsed += 1
            continue
        fp = simhash(f"{doc.title} {doc.text[:4000]}")
        candidates: set[int] = set()
        for band in range(4):
            candidates.update(bands.get((band, (fp >> (16 * band)) & 0xFFFF), []))
        duplicate_of = next((i for i in candidates if hamming(fp, prints[i]) <= max_distance), None)
        if duplicate_of is not None:
            kept[duplicate_of] = _better(kept[duplicate_of], doc)
            collapsed += 1
            continue
        idx = len(kept)
        kept.append(doc)
        prints.append(fp)
        if identity:
            seen_ids[identity] = idx
        for band in range(4):
            bands.setdefault((band, (fp >> (16 * band)) & 0xFFFF), []).append(idx)
    return kept, collapsed
