"""Clinical tagging of documents: biomarkers, histology, settings and drugs.

Tags are stored on every chunk. Retrieval uses them to boost passages that
name the same driver as the question and to penalise passages about a
different driver; the trial matcher uses them as structured filters.
"""

from __future__ import annotations

import re

from carina.clinical.understanding import HISTOLOGY_PATTERNS, SETTING_PATTERNS, detect_biomarkers, find_drugs


def tag_text(text: str) -> dict[str, list[str]]:
    lowered = text.lower()
    biomarkers = detect_biomarkers(lowered)
    histology_text = re.sub(r"non[\s-]?small[\s-]?cell", " nsclc ", lowered)
    histology = [code for code, pattern in HISTOLOGY_PATTERNS if pattern.search(histology_text)]
    settings = [code for code, pattern in SETTING_PATTERNS if pattern.search(lowered)]
    return {
        "biomarkers": biomarkers,
        "histology": histology,
        "settings": settings,
        "drugs": find_drugs(lowered),
    }
