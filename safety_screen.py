"""Medication safety screen for planned systemic anticancer therapy.

Checks what the team plans to give against the patient's current medicines,
conditions, allergies and renal function, using the reviewed rules in
safety_rules.yaml. The screen explains each flag and cites the SmPC section
it comes from; it never blocks a decision on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from carina.clinical.dosing import DosingError, creatinine_clearance
from carina.clinical.understanding import canonical_drug, classes_of, drug_class_members
from carina.domain import PatientContext
from carina.knowledge import load


@dataclass
class SafetyFlag:
    rule_id: str
    severity: str
    planned: str
    trigger: str
    message: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass
class ScreenResult:
    planned: list[str]
    flags: list[SafetyFlag] = field(default_factory=list)
    crcl_ml_min: float | None = None
    unknown_medicines: list[str] = field(default_factory=list)
    rules_version: int = 0
    last_reviewed: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "planned": self.planned,
            "flags": [flag.as_dict() for flag in self.flags],
            "highest_severity": self.flags[0].severity if self.flags else None,
            "crcl_ml_min": self.crcl_ml_min,
            "unknown_medicines": self.unknown_medicines,
            "rules_version": self.rules_version,
            "last_reviewed": self.last_reviewed,
            "disclaimer": "Curated screen for common lung cancer treatments. It does not replace the BNF interactions appendix or a pharmacist review.",
        }


@lru_cache(maxsize=1)
def _rules() -> dict[str, Any]:
    return load("safety_rules.yaml")


def _norm(items: list[str]) -> list[str]:
    out = []
    for item in items:
        name = canonical_drug(item) or item.lower().strip()
        out.append(name.replace("'", "").replace("’", ""))
    return out


def _planned_matches(rule: dict[str, Any], drug: str) -> bool:
    if drug in [d.lower() for d in rule.get("planned", [])]:
        return True
    return bool(set(rule.get("planned_class", [])) & set(classes_of(drug)))


def _contains(haystack: list[str], needles: list[str]) -> str | None:
    """Whole word match in either direction, so 'ild' never matches 'mild'."""
    for item in haystack:
        for needle in needles:
            if re.search(rf"\b{re.escape(needle)}\b", item) or re.search(rf"\b{re.escape(item)}\b", needle):
                return item
    return None


def screen(planned: list[str], ctx: PatientContext) -> ScreenResult:
    rules = _rules()
    planned_norm = _norm(planned)
    medicines = _norm(ctx.current_medicines)
    conditions = [c.lower().strip() for c in ctx.conditions]
    allergies = [a.lower().strip() for a in ctx.allergies]

    crcl = None
    if ctx.age and ctx.weight_kg and ctx.serum_creatinine_umol_l and ctx.sex in ("male", "female"):
        try:
            crcl = creatinine_clearance(ctx.age, ctx.weight_kg, ctx.serum_creatinine_umol_l, ctx.sex).value
        except DosingError:
            crcl = None

    known_classes = {
        name: drug_class_members(name)
        for name in (
            "strong_cyp3a_inducer",
            "strong_cyp3a_inhibitor",
            "acid_reducing",
            "qt_prolonging",
            "bradycardic",
            "nsaid",
            "anticoagulant",
            "nephrotoxic",
            "systemic_corticosteroid",
            "live_vaccine",
        )
    }
    unknown = [m for m in medicines if not canonical_drug(m) and not any(m in members for members in known_classes.values())]

    flags: list[SafetyFlag] = []
    for drug in planned_norm:
        for rule in rules["rules"]:
            if not _planned_matches(rule, drug):
                continue
            trigger = None
            if rule.get("always"):
                trigger = "always applies"
            if trigger is None and "with_medicine_class" in rule:
                members = drug_class_members(rule["with_medicine_class"])
                hit = _contains(medicines, members)
                if hit:
                    trigger = f"current medicine: {hit}"
            if trigger is None and "with_medicine" in rule:
                hit = _contains(medicines, [m.lower() for m in rule["with_medicine"]])
                if hit:
                    trigger = f"current medicine: {hit}"
            if trigger is None and "with_condition" in rule:
                hit = _contains(conditions, [c.lower() for c in rule["with_condition"]])
                if hit:
                    trigger = f"condition: {hit}"
            if trigger is None and "with_allergy" in rule:
                hit = _contains(allergies, [a.lower() for a in rule["with_allergy"]])
                if hit:
                    trigger = f"allergy: {hit}"
            if trigger is None and "crcl_below" in rule and crcl is not None and crcl < rule["crcl_below"]:
                trigger = f"creatinine clearance {crcl:.0f} mL/min"
            if trigger is None:
                continue
            flags.append(SafetyFlag(rule["id"], rule["severity"], drug, trigger, rule["message"], rule["source"]))

    order = {name: idx for idx, name in enumerate(rules["severity_order"])}
    flags.sort(key=lambda f: (order.get(f.severity, 99), f.planned))
    return ScreenResult(
        planned=planned_norm,
        flags=flags,
        crcl_ml_min=crcl,
        unknown_medicines=unknown,
        rules_version=int(rules["version"]),
        last_reviewed=str(rules["last_reviewed"]),
    )
