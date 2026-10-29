"""Scope control: the assistant answers thoracic oncology questions only.

A question with no lung cancer, oncology or relevant medicines content is
declined politely without spending a model call. A short follow up question
inherits scope from the conversation so "and in PS 2?" still works.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from carina.clinical.understanding import QueryUnderstanding

SCOPE_TERMS = re.compile(
    r"\b(lung|pulmonary|thoracic|thorax|bronch\w*|pleura\w*|mediastin\w*|nsclc|sclc|small[\s-]?cell|"
    r"adenocarcinoma|squamous|mesothelioma|carcinoid|nodule|mass|tumou?r|cancer|carcinoma|oncolog\w*|"
    r"metasta\w*|chemo\w*|radiotherapy|sabr|sbrt|chemoradio\w*|immunotherapy|checkpoint|"
    r"tki|targeted therapy|biomarker|egfr|alk|ros1|kras|braf|met|ret|ntrk|her2|pd[\s-]?l1|tps|tnm|"
    r"stage|staging|lobectomy|resection|pneumonectomy|ebus|pet[\s-]?ct|mdt|trial|neutropeni\w*|"
    r"pneumonitis|haemoptysis|hemoptysis|svco|spinal cord|cachexia|sact|nice|ng122|carboplatin|cisplatin|"
    r"pemetrexed|docetaxel|etoposide|calvert|auc|body surface area|creatinine clearance|performance status|ecog|karnofsky|"
    r"surgery|surgical|operable|inoperable|postoperative|fev1|tlco|spirometry|survival|disease free|progression free|"
    r"response rate|hazard ratio|fraction\w*|gy|irradiation|pci|sabr|smoking|biopsy|mri|ct)\b",
    re.I,
)

FOLLOW_UP = re.compile(r"^\s*(and|what about|how about|if|in|for|with|would|could|does|is|same|ok|okay|then|also)\b", re.I)


@dataclass(frozen=True)
class ScopeDecision:
    in_scope: bool
    reason: str


def known_terms_from_index(documents: Iterable[dict[str, Any]]) -> frozenset[str]:
    """Trial acronyms, NICE references and NCT numbers present in the index.

    A question naming one of them ("What did ALINA show?") is in scope even
    when it contains no other oncology vocabulary.
    """
    terms: set[str] = set()
    for doc in documents:
        identifiers = doc.get("identifiers", {})
        for key in ("trial", "nice", "nct"):
            value = identifiers.get(key)
            if value:
                terms.add(str(value).lower())
    return frozenset(terms)


def check_scope(question: str, understanding: QueryUnderstanding, history_in_scope: bool = False, known_terms: frozenset[str] = frozenset()) -> ScopeDecision:
    lowered = question.lower()
    if any(re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", lowered) for term in known_terms):
        return ScopeDecision(True, "names a trial or guidance document in the index")
    if understanding.drugs or understanding.biomarkers or understanding.tnm or understanding.histology:
        return ScopeDecision(True, "clinical entities found")
    if SCOPE_TERMS.search(question):
        return ScopeDecision(True, "thoracic oncology terms found")
    if history_in_scope and (len(question.split()) <= 14 or FOLLOW_UP.search(question)):
        return ScopeDecision(True, "follow up question in an in scope conversation")
    return ScopeDecision(False, "no lung cancer or oncology content")


OUT_OF_SCOPE_MESSAGE = (
    "Carina Compass answers questions about the diagnosis, staging and treatment of lung cancer "
    "for healthcare professionals. This question looks outside that scope, so no answer was generated."
)
