"""Clinical tokenizer for lexical retrieval.

General purpose tokenizers split exactly the tokens that matter most in
thoracic oncology: "L858R", "G12C", "PD-L1", "exon 19", "T2a", "mg/m2",
"TA654", "NCT06345729". This tokenizer keeps them whole, adds joined forms
("exon 19" also yields "exon19") and maps brand names to generics so a query
for "Tagrisso" finds a passage that says "osimertinib".
"""

from __future__ import annotations

import re
from functools import lru_cache

from carina.knowledge import load

TOKEN = re.compile(
    r"nct\d{8}|ta\d{2,4}|ng\d{2,4}|cg\d{2,4}|"  # registry and guidance identifiers
    r"pd-?l1|her2|erbb2|ros1|ntrk[123]?|"  # biomarkers with digits or hyphens
    r"[a-z]\d{2,4}[a-z]|"  # protein changes such as l858r, g12c, t790m, v600e
    r"[tnm][0-4x](?:mi|is|[abc]\d?)?|"  # tnm categories
    r"\d+(?:\.\d+)?(?:mg/m2|mg/kg|mg|ml/min|ml|gy|%)?|"  # numbers with clinical units
    r"[a-z][a-z0-9]+(?:-[a-z0-9]+)*",
    re.I,
)

ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv"}
STAGE = re.compile(r"\bstages?\s+(iv|i{1,3}|[1-4])([abc]\d?)?\b", re.I)

JOINERS = [
    (re.compile(r"\bexon\s+(\d{1,2})\b", re.I), r"exon\1"),
    (re.compile(r"\bpd[\s-]l1\b", re.I), "pdl1"),
    (re.compile(r"\bmg/m²", re.I), "mg/m2"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s+(mg/m2|mg/kg|mg|gy|ml/min)(?![\w/])", re.I), r"\1\2"),
]


@lru_cache(maxsize=1)
def _stopwords() -> frozenset[str]:
    return frozenset(load("lexicon.yaml")["stopwords"])


@lru_cache(maxsize=1)
def _brands() -> dict[str, str]:
    return dict(load("lexicon.yaml")["brand_to_generic"])


METASTATIC = re.compile(r"\b(metastatic|stage\s?(iv[ab]?|4[ab]?)|m1[abc]?\d?|distant metasta\w*)\b", re.I)


def concept_tokens(text: str) -> list[str]:
    """Canonical clinical concepts, so that 'exon 19 deletion' and 'EGFR mutation positive'
    share the token bm_egfr_common, and 'stage IVA' and 'metastatic' share phase_metastatic."""
    from carina.clinical.understanding import detect_biomarkers  # local import avoids a cycle at load time

    tokens = [f"bm_{code.lower()}" for code in detect_biomarkers(text)]
    if METASTATIC.search(text):
        tokens.append("phase_metastatic")
    return tokens


PROTECTED_ENDINGS = ("ss", "us", "is", "ous", "sis")


def stem(token: str) -> str:
    """A deliberately light suffix stripper for plain words.

    'declines' and 'decline', 'fractions' and 'fraction', 'tumours' and
    'tumour' meet; clinical identifiers, numbers and short words are untouched.
    """
    if len(token) <= 4 or not token.isalpha() or token.endswith(PROTECTED_ENDINGS):
        return token
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            token = token[: -len(suffix)] + replacement
            break
    if token.endswith("e") and len(token) > 5:
        token = token[:-1]
    return token


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    lowered = text.lower()
    # Clinical, pathological and post therapy prefixes (cT2a, pN1, ypT1b) index as the bare category.
    lowered = re.sub(r"\b(?:c|p|yp|r)(?=[tnm][0-4x](?:mi|is|[abc]\d?)?\b)", "", lowered)
    extra: list[str] = []
    for pattern, replacement in JOINERS:
        for match in pattern.finditer(lowered):
            extra.append(match.expand(replacement).lower())
    extra.extend(concept_tokens(lowered))
    for match in STAGE.finditer(lowered):
        roman = ROMAN.get(match.group(1), match.group(1).lower())
        suffix = (match.group(2) or "").lower()
        extra.extend([f"stage{roman}{suffix}", f"stage{roman}"])
    tokens = [t.lower().replace("pd-l1", "pdl1").replace("pd-l1", "pdl1") for t in TOKEN.findall(lowered)]
    tokens = [t.replace("pdl1", "pdl1") for t in tokens]
    brands = _brands()
    out: list[str] = []
    stop = _stopwords()
    for token in tokens + extra:
        if not keep_stopwords and token in stop:
            continue
        if len(token) == 1 and not token.isdigit():
            continue
        generic = brands.get(token)
        if generic:
            out.extend(generic.split())
        else:
            out.append(stem(token))
            if "-" in token:
                out.extend(part for part in token.split("-") if len(part) > 1 and part not in stop)
    return out
