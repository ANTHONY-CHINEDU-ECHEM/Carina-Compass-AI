"""Clinical trial matching over harvested ClinicalTrials.gov records.

Matching is a transparent prefilter on structured registry fields (status,
phase, age limits, sex, countries) and on the biomarker, histology and setting
tags extracted from each record at ingestion. It never claims a patient is
eligible: eligibility is decided by the trial team against the full criteria.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from carina.domain import PatientContext

OPEN_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
PHASE_WEIGHT = {"PHASE3": 3.0, "PHASE2_PHASE3": 2.5, "PHASE2": 2.0, "PHASE1_PHASE2": 1.5, "PHASE1": 1.0}


@dataclass
class TrialMatch:
    nct_id: str
    title: str
    url: str
    status: str
    status_verified: bool
    phases: list[str]
    score: float
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    uk_sites: list[str] = field(default_factory=list)
    last_update: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _age_years(value: str | None) -> float | None:
    if not value:
        return None
    parts = value.split()
    try:
        number = float(parts[0])
    except (ValueError, IndexError):
        return None
    unit = parts[1].lower() if len(parts) > 1 else "years"
    if unit.startswith("month"):
        return number / 12
    if unit.startswith("week"):
        return number / 52
    return number


def match_trials(
    ctx: PatientContext,
    trials: Iterable[dict[str, Any]],
    *,
    country: str = "United Kingdom",
    open_only: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    results: list[TrialMatch] = []
    considered = 0
    for meta in trials:
        considered += 1
        status = str(meta.get("overall_status") or "UNKNOWN").upper()
        verified = bool(meta.get("status_verified", status != "NOT_VERIFIED"))
        if open_only and verified and status not in OPEN_STATUSES:
            continue

        reasons: list[str] = []
        cautions: list[str] = []
        score = 0.0

        trial_biomarkers = set(meta.get("biomarkers", []))
        patient_biomarkers = set(ctx.biomarkers)
        if trial_biomarkers:
            overlap = trial_biomarkers & patient_biomarkers
            if overlap:
                score += 4.0
                reasons.append("biomarker match: " + ", ".join(sorted(overlap)))
            elif patient_biomarkers:
                continue
            else:
                cautions.append("Trial requires " + ", ".join(sorted(trial_biomarkers)) + "; patient molecular profile not supplied.")
                score -= 1.0

        trial_histology = set(meta.get("histology", []))
        if trial_histology and ctx.histology:
            compatible = (
                ctx.histology in trial_histology
                or ("nsclc" in trial_histology and ctx.histology not in ("small_cell", "mesothelioma"))
                or ("non_squamous" in trial_histology and ctx.histology in ("adenocarcinoma", "large_cell"))
            )
            if not compatible:
                continue
            score += 1.5
            reasons.append(f"histology: {ctx.histology}")

        trial_settings = set(meta.get("settings", []))
        if trial_settings and ctx.setting:
            if ctx.setting in trial_settings:
                score += 1.5
                reasons.append(f"setting: {ctx.setting}")
            else:
                score -= 0.5
                cautions.append("Setting differs: trial lists " + ", ".join(sorted(trial_settings)))

        min_age, max_age = _age_years(meta.get("minimum_age")), _age_years(meta.get("maximum_age"))
        if ctx.age is not None:
            if min_age is not None and ctx.age < min_age:
                continue
            if max_age is not None and ctx.age > max_age:
                continue
        sex = str(meta.get("sex") or "ALL").upper()
        if ctx.sex and sex in ("MALE", "FEMALE") and sex.lower() != ctx.sex.lower():
            continue

        phases = [str(p).upper() for p in meta.get("phases", [])]
        phase_key = "_".join(sorted(phases)) if len(phases) > 1 else (phases[0] if phases else "")
        score += PHASE_WEIGHT.get(phase_key, 0.5)

        countries = [str(c) for c in meta.get("countries", [])]
        uk_sites = [str(s) for s in meta.get("uk_sites", [])]
        if country and countries:
            if country in countries:
                score += 2.0
                reasons.append(f"sites in {country}")
            else:
                score -= 1.0
                cautions.append(f"No listed sites in {country}.")
        elif country:
            cautions.append("Site countries not available in this record.")

        if not verified:
            cautions.append("Recruitment status not verified in the seed snapshot; refresh from ClinicalTrials.gov before referral.")

        nct = str(meta.get("nct_id"))
        results.append(
            TrialMatch(
                nct_id=nct,
                title=str(meta.get("title", "")),
                url=f"https://clinicaltrials.gov/study/{nct}",
                status=status,
                status_verified=verified,
                phases=phases,
                score=round(score, 2),
                reasons=reasons,
                cautions=cautions,
                uk_sites=uk_sites,
                last_update=meta.get("last_update"),
            )
        )

    results.sort(key=lambda r: (-r.score, r.nct_id))
    return {
        "considered": considered,
        "matches": [r.as_dict() for r in results[:limit]],
        "country": country,
        "open_only": open_only,
        "disclaimer": "Registry prefilter only. Eligibility is confirmed by the trial team against the full protocol criteria.",
    }
