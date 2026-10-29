"""Biomarker and setting matched treatment options.

The matcher reads therapy_matrix.yaml and returns the options whose
constraints fit the de identified patient context. It reports why each option
matched and, just as importantly, what information is missing, so the MDT can
see when a recommendation rests on an assumption. It never returns a dose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from carina.clinical.understanding import classes_of
from carina.domain import PatientContext
from carina.knowledge import load

STATUS_ORDER = {
    "recommended": 0,
    "recommended_cdf": 1,
    "see_appraisal": 2,
    "not_recommended": 3,
    "terminated": 4,
}

STATUS_LABEL = {
    "recommended": "Recommended by NICE",
    "recommended_cdf": "Available through the Cancer Drugs Fund",
    "see_appraisal": "Check the appraisal for the eligible population",
    "not_recommended": "Not recommended by NICE",
    "terminated": "Appraisal terminated, no NICE recommendation",
}

ADVANCED_SETTINGS = {"advanced_first_line", "advanced_subsequent", "advanced_any_line"}


@dataclass
class TherapyOption:
    option_id: str
    regimen: str
    setting: str
    drugs: list[str]
    nice_reference: str
    nice_status: str
    nice_status_label: str
    guideline: str | None
    evidence_trial: str | None
    evidence_pmid: str | None
    notes: str | None
    matched_on: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    rank: int = 9

    def as_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "regimen": self.regimen,
            "setting": self.setting,
            "drugs": self.drugs,
            "nice_reference": self.nice_reference,
            "nice_status": self.nice_status,
            "nice_status_label": self.nice_status_label,
            "guideline": self.guideline,
            "evidence_trial": self.evidence_trial,
            "evidence_pmid": self.evidence_pmid,
            "evidence_url": f"https://pubmed.ncbi.nlm.nih.gov/{self.evidence_pmid}/" if self.evidence_pmid else None,
            "nice_url": _nice_url(self.nice_reference),
            "notes": self.notes,
            "matched_on": self.matched_on,
            "caveats": self.caveats,
        }


@dataclass
class TherapyMatch:
    setting: str | None
    options: list[TherapyOption]
    missing_information: list[str]
    assumptions: list[str]
    matrix_version: int
    last_reviewed: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "setting": self.setting,
            "options": [option.as_dict() for option in self.options],
            "missing_information": self.missing_information,
            "assumptions": self.assumptions,
            "matrix_version": self.matrix_version,
            "last_reviewed": self.last_reviewed,
            "disclaimer": "Options listed for MDT discussion. Confirm eligibility against the full NICE appraisal, the SmPC and the local SACT protocol.",
        }


def _nice_url(reference: str) -> str | None:
    head = reference.split()[0]
    if head.upper().startswith(("TA", "NG", "CG")):
        return f"https://www.nice.org.uk/guidance/{head.lower()}"
    return None


@lru_cache(maxsize=1)
def _matrix() -> dict[str, Any]:
    return load("therapy_matrix.yaml")


def infer_setting(ctx: PatientContext) -> tuple[str | None, list[str]]:
    """Infer the treatment setting from stage, histology and prior treatment."""
    assumptions: list[str] = []
    if ctx.setting:
        return ctx.setting, assumptions
    stage = (ctx.stage_group or "").upper()
    if ctx.histology == "small_cell":
        if stage.startswith("IV") or (ctx.m_category or "M0").upper() != "M0":
            assumptions.append("Metastatic small cell disease treated as extensive stage.")
            return "extensive_stage_sclc", assumptions
        if stage:
            assumptions.append("Non metastatic small cell disease treated as limited stage.")
            return "limited_stage_sclc", assumptions
        return None, assumptions
    if stage.startswith("IV") or (ctx.m_category and ctx.m_category.upper() != "M0"):
        if ctx.prior_treatments or (ctx.line_of_therapy or 1) > 1:
            return "advanced_subsequent", assumptions
        assumptions.append("No prior systemic treatment recorded; first line setting assumed.")
        return "advanced_first_line", assumptions
    if stage in ("IIIB", "IIIC"):
        assumptions.append("Stage IIIB to IIIC treated as unresectable; confirm at MDT.")
        return "unresectable_stage3", assumptions
    return None, assumptions


def _histology_ok(required: str, histology: str | None) -> bool:
    if required in ("any", None):
        return True
    if histology is None:
        return required != "small_cell"
    if required == "nsclc":
        return histology != "small_cell"
    if required == "non_squamous":
        return histology in ("non_squamous", "adenocarcinoma", "large_cell", "nsclc")
    if required == "adenocarcinoma":
        return histology == "adenocarcinoma"
    return required == histology


def _setting_ok(option_setting: str, setting: str | None) -> bool:
    if setting is None:
        return False
    if option_setting == setting:
        return True
    return option_setting == "advanced_any_line" and setting in ADVANCED_SETTINGS


def match_therapies(ctx: PatientContext, *, include_not_recommended: bool = True) -> TherapyMatch:
    matrix = _matrix()
    setting, assumptions = infer_setting(ctx)
    missing: list[str] = []
    if setting is None:
        missing.append("treatment setting or stage")
    if ctx.histology is None:
        missing.append("histology")
    if setting in ADVANCED_SETTINGS and ctx.histology != "small_cell":
        if not ctx.biomarkers:
            missing.append("molecular profile (EGFR, ALK, ROS1, KRAS, BRAF, MET, RET, NTRK, HER2)")
        if ctx.pdl1_tps is None:
            missing.append("PD L1 tumour proportion score")
    if ctx.performance_status is None:
        missing.append("performance status")

    biomarkers = set(ctx.biomarkers)
    prior_classes = {cls for drug in ctx.prior_treatments for cls in classes_of(drug)}
    prior_drugs = {drug.lower() for drug in ctx.prior_treatments}
    has_driver = bool(biomarkers - {"KRAS_G12C", "HER2_MUT"})

    options: list[TherapyOption] = []
    for item in matrix["options"]:
        if not _setting_ok(item["setting"], setting):
            continue
        if not _histology_ok(item.get("histology", "any"), ctx.histology):
            continue
        matched_on = [f"setting: {setting}"]
        caveats: list[str] = []

        required = set(item.get("biomarkers_any", []))
        if required:
            if not required & biomarkers:
                continue
            matched_on.append("biomarker: " + ", ".join(sorted(required & biomarkers)))
        elif setting in ADVANCED_SETTINGS and has_driver and item["setting"] != "advanced_subsequent":
            # Driver positive disease is treated with targeted therapy first;
            # immunotherapy based first line options are not shown.
            continue

        excluded = set(item.get("biomarkers_excluded", []))
        if excluded & biomarkers:
            continue
        if excluded and not ctx.biomarkers:
            caveats.append("Requires " + ", ".join(sorted(excluded)) + " to be excluded; molecular results not supplied.")

        pdl1_min = item.get("pdl1_min")
        if pdl1_min is not None:
            if ctx.pdl1_tps is None:
                caveats.append(f"Requires PD L1 at least {pdl1_min}%; result not supplied.")
            elif ctx.pdl1_tps < pdl1_min:
                continue
            else:
                matched_on.append(f"PD L1 {ctx.pdl1_tps:g}% (threshold {pdl1_min}%)")

        ps_max = item.get("ps_max")
        if ps_max is not None and ctx.performance_status is not None and ctx.performance_status > ps_max:
            continue
        if ps_max is not None and ctx.performance_status is None:
            caveats.append(f"Requires performance status {ps_max} or better.")

        prior_class = item.get("requires_prior_class")
        if prior_class and prior_class not in prior_classes:
            if ctx.prior_treatments:
                continue
            caveats.append(f"Requires earlier treatment with an agent in class {prior_class.replace('_', ' ')}.")
        prior_drug = item.get("requires_prior_drug")
        if prior_drug and prior_drug not in prior_drugs:
            if ctx.prior_treatments:
                continue
            caveats.append(f"Requires earlier treatment with {prior_drug}.")

        status = item["nice"]["status"]
        if not include_not_recommended and status in ("not_recommended", "terminated"):
            continue
        evidence = item.get("evidence") or {}
        options.append(
            TherapyOption(
                option_id=item["id"],
                regimen=item["regimen"],
                setting=item["setting"],
                drugs=list(item.get("drugs", [])),
                nice_reference=str(item["nice"]["reference"]),
                nice_status=status,
                nice_status_label=STATUS_LABEL[status],
                guideline=item.get("guideline"),
                evidence_trial=evidence.get("trial"),
                evidence_pmid=evidence.get("pmid"),
                notes=item.get("notes"),
                matched_on=matched_on,
                caveats=caveats,
                rank=int(item.get("rank", 9)),
            )
        )

    options.sort(key=lambda opt: (STATUS_ORDER[opt.nice_status], opt.rank, opt.regimen))
    return TherapyMatch(
        setting=setting,
        options=options,
        missing_information=missing,
        assumptions=assumptions,
        matrix_version=int(matrix["version"]),
        last_reviewed=str(matrix["last_reviewed"]),
    )
