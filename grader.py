"""Evidence grading on the seven step ladder.

UK national guidance       7  NICE guidelines and technology appraisals
International guidance     6  NCI PDQ evidence summaries, international guidelines
Systematic review          5  PubMed or Europe PMC records typed as systematic review or meta analysis; CIViC level A
Randomised trial           4  Records typed as randomised or phase 3 trials; CIViC level B
Observational/regulatory   3  Cohorts, early phase trials, drug labels, staging references
Case report                2  Case reports and series; CIViC level C
Expert opinion             1  Narrative reviews, editorials, registry entries, patient information; CIViC levels D and E
"""

from __future__ import annotations

from carina.domain import EvidenceGrade, SourceType

PUBLICATION_TYPE_GRADES: list[tuple[tuple[str, ...], EvidenceGrade]] = [
    (("practice guideline", "guideline", "consensus development conference"), EvidenceGrade.INTERNATIONAL_GUIDANCE),
    (("systematic review", "meta-analysis", "meta analysis", "network meta-analysis"), EvidenceGrade.SYSTEMATIC_REVIEW),
    (
        ("randomized controlled trial", "randomised controlled trial", "clinical trial, phase iii", "equivalence trial", "pragmatic clinical trial"),
        EvidenceGrade.RANDOMISED_TRIAL,
    ),
    (
        (
            "clinical trial, phase ii",
            "clinical trial, phase i",
            "clinical trial",
            "observational study",
            "comparative study",
            "multicenter study",
            "cohort",
            "evaluation study",
            "validation study",
        ),
        EvidenceGrade.OBSERVATIONAL_OR_REGULATORY,
    ),
    (("case reports", "case report", "case series"), EvidenceGrade.CASE_REPORT),
    (("review", "editorial", "comment", "letter", "news", "lecture"), EvidenceGrade.EXPERT_OPINION),
]

CIVIC_LEVELS = {
    "A": EvidenceGrade.SYSTEMATIC_REVIEW,
    "B": EvidenceGrade.RANDOMISED_TRIAL,
    "C": EvidenceGrade.CASE_REPORT,
    "D": EvidenceGrade.EXPERT_OPINION,
    "E": EvidenceGrade.EXPERT_OPINION,
}

SOURCE_DEFAULTS = {
    SourceType.NICE_GUIDELINE: EvidenceGrade.UK_NATIONAL_GUIDANCE,
    SourceType.NICE_APPRAISAL: EvidenceGrade.UK_NATIONAL_GUIDANCE,
    SourceType.PDQ: EvidenceGrade.INTERNATIONAL_GUIDANCE,
    SourceType.DRUG_LABEL: EvidenceGrade.OBSERVATIONAL_OR_REGULATORY,
    SourceType.STAGING_REFERENCE: EvidenceGrade.OBSERVATIONAL_OR_REGULATORY,
    SourceType.CLINICAL_TRIAL: EvidenceGrade.EXPERT_OPINION,
    SourceType.PATIENT_INFO: EvidenceGrade.EXPERT_OPINION,
}


def grade_publication_types(types: list[str]) -> EvidenceGrade:
    lowered = [t.lower() for t in types]
    for keys, grade in PUBLICATION_TYPE_GRADES:
        if any(key == t or key in t for t in lowered for key in keys):
            return grade
    return EvidenceGrade.UNGRADED


def grade(source: SourceType, publication_types: list[str] | None = None, civic_level: str | None = None, title: str = "") -> EvidenceGrade:
    if source in SOURCE_DEFAULTS:
        return SOURCE_DEFAULTS[source]
    if source == SourceType.CIVIC and civic_level:
        return CIVIC_LEVELS.get(civic_level.upper(), EvidenceGrade.EXPERT_OPINION)
    graded = grade_publication_types(publication_types or [])
    if graded == EvidenceGrade.UNGRADED and title:
        lowered = title.lower()
        if "meta-analysis" in lowered or "systematic review" in lowered:
            return EvidenceGrade.SYSTEMATIC_REVIEW
        if "randomized" in lowered or "randomised" in lowered or "phase 3" in lowered or "phase iii" in lowered:
            return EvidenceGrade.RANDOMISED_TRIAL
    return graded
