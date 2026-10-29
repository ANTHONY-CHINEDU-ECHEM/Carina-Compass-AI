"""Text normalisation that never destroys clinical tokens.

Generic cleaners strip exactly the characters oncology depends on: the
greater than or equal sign in "PD-L1 ≥50%", the superscript in "mg/m²", the
hyphen in "exon 19", the decimal point in "HR 0.46". This cleaner normalises
whitespace, quotes and markup while preserving them.
"""

from __future__ import annotations

import html
import re
import unicodedata

TAG = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"[ \t   ]+")
NEWLINES = re.compile(r"\n{3,}")
BOILERPLATE = [
    re.compile(r"^\s*(copyright|©).{0,200}$", re.I | re.M),
    re.compile(r"^\s*(this article is protected by copyright|all rights reserved).*$", re.I | re.M),
    re.compile(r"^\s*(skip to (main )?content|cookie(s)? (policy|settings)|accept all cookies).*$", re.I | re.M),
]
REPLACEMENTS = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "mg/m²": "mg/m2",
    "m²": "m2",
    "μ": "micro",
    "µ": "micro",
    "≥": "≥",
    "≤": "≤",
}


def clean_text(text: str, *, strip_markup: bool = True) -> str:
    if not text:
        return ""
    out = html.unescape(text)
    if strip_markup:
        out = TAG.sub(" ", out)
    out = unicodedata.normalize("NFC", out)
    for old, new in REPLACEMENTS.items():
        out = out.replace(old, new)
    for pattern in BOILERPLATE:
        out = pattern.sub("", out)
    out = WHITESPACE.sub(" ", out)
    out = re.sub(r" *\n *", "\n", out)
    out = NEWLINES.sub("\n\n", out)
    return out.strip()


def strip_structured_abstract_labels(text: str) -> str:
    """Keep structured abstract labels as sentence starts (BACKGROUND: becomes Background.)."""
    return re.sub(r"\b(BACKGROUND|METHODS|RESULTS|CONCLUSIONS?|OBJECTIVES?|PURPOSE|FINDINGS|INTERPRETATION)\s*:\s*", lambda m: m.group(1).title() + ". ", text)
