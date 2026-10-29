"""Deterministic dose calculators for systemic anticancer therapy.

Only well established formulae are implemented, each with the guard rails a
chemotherapy pharmacist would apply. The results are a check for the
prescriber, not a prescription: the local SACT protocol, dose banding and the
treating oncologist always decide the final dose.

Formulae
  Body surface area (Mosteller): sqrt(height_cm x weight_kg / 3600)
  Body surface area (DuBois): 0.007184 x weight^0.425 x height^0.725
  Creatinine clearance (Cockcroft and Gault, SI units):
      (140 minus age) x weight x F / serum creatinine, F = 1.23 for men, 1.04 for women
  Carboplatin (Calvert): dose mg = target AUC x (GFR + 25)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

GFR_CAP_ML_MIN = 125.0
MAX_AUC = 7.0


class DosingError(ValueError):
    """Raised for inputs outside physiologically plausible ranges."""


@dataclass
class DoseResult:
    calculation: str
    value: float
    unit: str
    inputs: dict[str, float | str]
    working: list[str]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "calculation": self.calculation,
            "value": self.value,
            "unit": self.unit,
            "inputs": self.inputs,
            "working": self.working,
            "warnings": self.warnings,
            "disclaimer": "Calculation check only. Confirm against the local SACT protocol and pharmacist verification before prescribing.",
        }


def _check(name: str, value: float, low: float, high: float) -> None:
    if not (low <= value <= high) or math.isnan(value):
        raise DosingError(f"{name} {value} is outside the plausible range {low} to {high}")


def body_surface_area(height_cm: float, weight_kg: float, method: str = "mosteller") -> DoseResult:
    _check("height_cm", height_cm, 100, 250)
    _check("weight_kg", weight_kg, 25, 300)
    if method == "mosteller":
        value = math.sqrt(height_cm * weight_kg / 3600)
        working = [f"sqrt({height_cm:g} x {weight_kg:g} / 3600) = {value:.3f}"]
    elif method == "dubois":
        value = 0.007184 * weight_kg**0.425 * height_cm**0.725
        working = [f"0.007184 x {weight_kg:g}^0.425 x {height_cm:g}^0.725 = {value:.3f}"]
    else:
        raise DosingError("method must be mosteller or dubois")
    warnings = []
    if value > 2.0:
        warnings.append("BSA above 2.0 m2: check whether the local protocol caps BSA or uses dose banding.")
    bmi = weight_kg / (height_cm / 100) ** 2
    if bmi >= 30:
        warnings.append(f"BMI {bmi:.1f}: obesity does not by itself justify capping the BSA (ASCO guideline); follow local policy.")
    return DoseResult(
        calculation=f"Body surface area ({method.title()})",
        value=round(value, 2),
        unit="m2",
        inputs={"height_cm": height_cm, "weight_kg": weight_kg, "method": method},
        working=working,
        warnings=warnings,
    )


def creatinine_clearance(age: int, weight_kg: float, serum_creatinine_umol_l: float, sex: str) -> DoseResult:
    _check("age", age, 18, 110)
    _check("weight_kg", weight_kg, 25, 300)
    _check("serum_creatinine_umol_l", serum_creatinine_umol_l, 20, 1500)
    sex_key = sex.lower()
    if sex_key not in ("male", "female"):
        raise DosingError("sex must be male or female for the Cockcroft and Gault equation")
    factor = 1.23 if sex_key == "male" else 1.04
    value = (140 - age) * weight_kg * factor / serum_creatinine_umol_l
    warnings = []
    if value < 30:
        warnings.append("Estimated clearance below 30 mL/min: most platinum and pemetrexed regimens need specialist review.")
    return DoseResult(
        calculation="Creatinine clearance (Cockcroft and Gault)",
        value=round(value, 1),
        unit="mL/min",
        inputs={"age": age, "weight_kg": weight_kg, "serum_creatinine_umol_l": serum_creatinine_umol_l, "sex": sex_key},
        working=[f"(140 minus {age}) x {weight_kg:g} x {factor} / {serum_creatinine_umol_l:g} = {value:.1f} mL/min"],
        warnings=warnings,
    )


def carboplatin_calvert(target_auc: float, gfr_ml_min: float, *, gfr_source: str = "estimated", cap_gfr: bool = True) -> DoseResult:
    _check("target_auc", target_auc, 1, MAX_AUC)
    _check("gfr_ml_min", gfr_ml_min, 5, 250)
    warnings: list[str] = []
    used_gfr = gfr_ml_min
    working = []
    if cap_gfr and gfr_ml_min > GFR_CAP_ML_MIN:
        used_gfr = GFR_CAP_ML_MIN
        warnings.append(f"GFR capped at {GFR_CAP_ML_MIN:g} mL/min, as most UK carboplatin protocols require.")
        working.append(f"GFR {gfr_ml_min:g} capped to {used_gfr:g} mL/min")
    if gfr_source != "measured":
        warnings.append(
            "The Calvert formula was derived with measured GFR (for example isotope GFR); an estimate from Cockcroft and Gault is less accurate at extremes of weight and renal function."
        )
    if gfr_ml_min < 30:
        warnings.append("GFR below 30 mL/min: carboplatin dosing needs oncologist and pharmacist review.")
    dose = target_auc * (used_gfr + 25)
    working.append(f"{target_auc:g} x ({used_gfr:g} + 25) = {dose:.0f} mg")
    return DoseResult(
        calculation="Carboplatin dose (Calvert formula)",
        value=round(dose),
        unit="mg",
        inputs={"target_auc": target_auc, "gfr_ml_min": gfr_ml_min, "gfr_source": gfr_source},
        working=working,
        warnings=warnings,
    )


def carboplatin_from_patient(target_auc: float, age: int, weight_kg: float, serum_creatinine_umol_l: float, sex: str) -> list[DoseResult]:
    """Chain Cockcroft and Gault into Calvert, returning both steps."""
    crcl = creatinine_clearance(age, weight_kg, serum_creatinine_umol_l, sex)
    dose = carboplatin_calvert(target_auc, crcl.value, gfr_source="estimated")
    return [crcl, dose]


ECOG_TO_KARNOFSKY = {0: (90, 100), 1: (70, 80), 2: (50, 60), 3: (30, 40), 4: (10, 20)}


def performance_status_mapping(ecog: int | None = None, karnofsky: int | None = None) -> dict[str, object]:
    """Approximate mapping between ECOG (WHO) and Karnofsky scores."""
    if ecog is not None:
        if ecog not in ECOG_TO_KARNOFSKY:
            raise DosingError("ECOG must be 0 to 4")
        low, high = ECOG_TO_KARNOFSKY[ecog]
        return {"ecog": ecog, "karnofsky_range": [low, high], "note": "Approximate correspondence; the scales were not designed to map exactly."}
    if karnofsky is not None:
        _check("karnofsky", karnofsky, 0, 100)
        for score, (low, high) in ECOG_TO_KARNOFSKY.items():
            if low <= karnofsky <= high:
                return {"karnofsky": karnofsky, "ecog": score, "note": "Approximate correspondence; the scales were not designed to map exactly."}
        return {"karnofsky": karnofsky, "ecog": 4 if karnofsky < 30 else 0, "note": "Approximate correspondence."}
    raise DosingError("Provide an ECOG or a Karnofsky score")
