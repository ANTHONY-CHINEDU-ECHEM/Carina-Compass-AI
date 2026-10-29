"""TNM staging for lung cancer, 8th and 9th editions.

The 9th edition (IASLC proposals, adopted by UICC and AJCC version 9) keeps the
T descriptors of the 8th edition but splits N2 into N2a (single ipsilateral
mediastinal or subcarinal station) and N2b (multiple stations), and M1c into
M1c1 (multiple extrathoracic metastases in one organ system) and M1c2 (several
organ systems). Four stage groups changed: T1N1 moved from IIB to IIA, T1N2a
became IIB, T2N2b became IIIB and T3N2a became IIIA.

References
  Rami-Porta R, et al. J Thorac Oncol 2024;19(7):1007 to 1027 (9th edition stage groups).
  Detterbeck FC, et al. Chest 2017;151(1):193 to 203 (8th edition).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

T_CATEGORIES = ("TX", "T0", "Tis", "T1mi", "T1a", "T1b", "T1c", "T2a", "T2b", "T3", "T4")
N_CATEGORIES_8 = ("NX", "N0", "N1", "N2", "N3")
N_CATEGORIES_9 = ("NX", "N0", "N1", "N2a", "N2b", "N3")
M_CATEGORIES_8 = ("M0", "M1a", "M1b", "M1c")
M_CATEGORIES_9 = ("M0", "M1a", "M1b", "M1c1", "M1c2")

_T_GROUP = {
    "T1mi": "T1",
    "T1a": "T1",
    "T1b": "T1",
    "T1c": "T1",
    "T2a": "T2",
    "T2b": "T2",
    "T3": "T3",
    "T4": "T4",
}

# Stage groups for N0 depend on the T subcategory; N1 and beyond depend on T group.
_N0 = {"T1mi": "IA1", "T1a": "IA1", "T1b": "IA2", "T1c": "IA3", "T2a": "IB", "T2b": "IIA", "T3": "IIB", "T4": "IIIA"}

_EDITION_8 = {
    ("T1", "N1"): "IIB",
    ("T2", "N1"): "IIB",
    ("T3", "N1"): "IIIA",
    ("T4", "N1"): "IIIA",
    ("T1", "N2"): "IIIA",
    ("T2", "N2"): "IIIA",
    ("T3", "N2"): "IIIB",
    ("T4", "N2"): "IIIB",
    ("T1", "N3"): "IIIB",
    ("T2", "N3"): "IIIB",
    ("T3", "N3"): "IIIC",
    ("T4", "N3"): "IIIC",
}

_EDITION_9 = {
    ("T1", "N1"): "IIA",
    ("T2", "N1"): "IIB",
    ("T3", "N1"): "IIIA",
    ("T4", "N1"): "IIIA",
    ("T1", "N2a"): "IIB",
    ("T2", "N2a"): "IIIA",
    ("T3", "N2a"): "IIIA",
    ("T4", "N2a"): "IIIB",
    ("T1", "N2b"): "IIIA",
    ("T2", "N2b"): "IIIB",
    ("T3", "N2b"): "IIIB",
    ("T4", "N2b"): "IIIB",
    ("T1", "N3"): "IIIB",
    ("T2", "N3"): "IIIB",
    ("T3", "N3"): "IIIC",
    ("T4", "N3"): "IIIC",
}

_M_STAGE_8 = {"M1a": "IVA", "M1b": "IVA", "M1c": "IVB"}
_M_STAGE_9 = {"M1a": "IVA", "M1b": "IVA", "M1c1": "IVB", "M1c2": "IVB"}

_CHANGED_IN_9 = {("T1", "N1"), ("T1", "N2a"), ("T2", "N2b"), ("T3", "N2a")}


@dataclass(frozen=True)
class StageResult:
    edition: int
    t: str
    n: str
    m: str
    stage_group: str
    broad_stage: str
    resectability_hint: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "edition": self.edition,
            "t": self.t,
            "n": self.n,
            "m": self.m,
            "stage_group": self.stage_group,
            "broad_stage": self.broad_stage,
            "resectability_hint": self.resectability_hint,
            "notes": list(self.notes),
        }


class StagingError(ValueError):
    """Raised when a TNM combination is incomplete or not valid for the edition."""


def _normalise(value: str, allowed: tuple[str, ...], kind: str) -> str:
    cleaned = value.strip().replace(" ", "")
    if not cleaned:
        raise StagingError(f"{kind} category is missing")
    if cleaned[0].upper() != kind:
        cleaned = kind + cleaned
    lookup = {item.lower(): item for item in allowed}
    found = lookup.get(cleaned.lower())
    if found is None:
        raise StagingError(f"{value!r} is not a valid {kind} category for this edition; expected one of {', '.join(allowed)}")
    return found


def stage(t: str, n: str, m: str, edition: int = 9) -> StageResult:
    """Return the stage group for a TNM combination."""
    if edition not in (8, 9):
        raise StagingError("edition must be 8 or 9")
    n_allowed = N_CATEGORIES_9 if edition == 9 else N_CATEGORIES_8
    m_allowed = M_CATEGORIES_9 if edition == 9 else M_CATEGORIES_8
    t_norm = _normalise(t, T_CATEGORIES, "T")
    n_norm = _normalise(n, n_allowed, "N")
    m_norm = _normalise(m, m_allowed, "M")
    notes: list[str] = []

    if m_norm != "M0":
        group = (_M_STAGE_9 if edition == 9 else _M_STAGE_8)[m_norm]
        notes.append("Any T and any N with distant metastasis.")
        return _result(edition, t_norm, n_norm, m_norm, group, notes)

    if t_norm in ("TX", "T0") or n_norm == "NX":
        if t_norm == "TX" and n_norm == "N0":
            return _result(edition, t_norm, n_norm, m_norm, "Occult carcinoma", ["Malignant cells in sputum or washings without a visible primary."])
        raise StagingError("T and N must both be assessable to assign a stage group without distant metastasis")
    if t_norm == "Tis":
        if n_norm != "N0":
            raise StagingError("Tis is only staged with N0 M0")
        return _result(edition, t_norm, n_norm, m_norm, "0", ["Carcinoma in situ."])

    if n_norm == "N0":
        return _result(edition, t_norm, n_norm, m_norm, _N0[t_norm], notes)

    table = _EDITION_9 if edition == 9 else _EDITION_8
    key = (_T_GROUP[t_norm], n_norm)
    group = table[key]
    if edition == 9 and key in _CHANGED_IN_9:
        eighth_n = "N2" if n_norm.startswith("N2") else n_norm
        eighth = _EDITION_8[(_T_GROUP[t_norm], eighth_n)]
        notes.append(f"This combination changed from stage {eighth} in the 8th edition to {group} in the 9th edition.")
    return _result(edition, t_norm, n_norm, m_norm, group, notes)


def _result(edition: int, t: str, n: str, m: str, group: str, notes: list[str]) -> StageResult:
    broad = _broad(group)
    return StageResult(
        edition=edition,
        t=t,
        n=n,
        m=m,
        stage_group=group,
        broad_stage=broad,
        resectability_hint=_hint(group, n),
        notes=notes,
    )


def _broad(group: str) -> str:
    if group.startswith("IV"):
        return "IV"
    if group.startswith("III"):
        return "III"
    if group.startswith("II"):
        return "II"
    if group.startswith("I"):
        return "I"
    return group


def _hint(group: str, n: str) -> str:
    if group.startswith("IV"):
        return "Metastatic disease: systemic therapy guided by histology, biomarkers and PD L1; consider local consolidative treatment only for oligometastatic disease in an MDT."
    if group in ("IIIB", "IIIC"):
        return "Usually unresectable: assess for concurrent chemoradiotherapy and consolidation immunotherapy (NG122 1.6.17 to 1.6.18)."
    if group == "IIIA":
        return "Potentially resectable in selected patients after MDT review; perioperative systemic therapy or multimodality treatment may apply (NG122 1.6)."
    if group.startswith("II") or group.startswith("I"):
        if n.startswith("N2"):
            return "Single station N2 disease: discuss multimodality treatment at the MDT."
        return "Early stage: lobectomy if fit; SABR or sublobar resection when surgery is declined or unsuitable (NG122 1.5)."
    return "Discuss at the lung cancer MDT."


def t_from_size(
    size_mm: float,
    *,
    invasive_mm: float | None = None,
    main_bronchus: bool = False,
    visceral_pleura: bool = False,
    atelectasis_to_hilum: bool = False,
    chest_wall_or_pericardium: bool = False,
    separate_nodule_same_lobe: bool = False,
    mediastinum_or_great_vessels: bool = False,
    separate_nodule_other_ipsilateral_lobe: bool = False,
) -> str:
    """Assign the T category from tumour size and invasion descriptors.

    The highest category reached by any descriptor wins. Size boundaries follow
    the 8th and 9th editions, which share T descriptors.
    """
    if size_mm <= 0:
        raise StagingError("tumour size must be positive")
    if mediastinum_or_great_vessels or separate_nodule_other_ipsilateral_lobe or size_mm > 70:
        return "T4"
    if chest_wall_or_pericardium or separate_nodule_same_lobe or size_mm > 50:
        return "T3"
    descriptor_t2 = main_bronchus or visceral_pleura or atelectasis_to_hilum
    if size_mm > 40:
        return "T2b"
    if size_mm > 30 or descriptor_t2:
        return "T2a"
    if invasive_mm is not None and size_mm <= 30 and invasive_mm <= 5:
        return "T1mi"
    if size_mm > 20:
        return "T1c"
    if size_mm > 10:
        return "T1b"
    return "T1a"


_TNM_PATTERN = re.compile(
    r"\b(?:[cpy]{0,2})(T(?:is|x|0|1mi|1[abc]?|2[ab]?|3|4))\s*,?\s*(N(?:x|0|1|2[ab]?|3))\s*,?\s*(M(?:0|1[ab]|1c[12]?|1))?",
    re.IGNORECASE,
)


def parse_tnm(text: str) -> tuple[str, str, str] | None:
    """Find a TNM string such as 'cT2a N2b M0' or 'T1cN1M0' in free text."""
    match = _TNM_PATTERN.search(text)
    if not match:
        return None
    t, n, m = match.group(1), match.group(2), match.group(3) or "M0"
    t = "T" + t[1:].lower() if not t[1:].lower().startswith("is") else "Tis"
    t = t.replace("tx", "TX")
    n = "N" + n[1:].lower()
    m = "M" + m[1:].lower()
    return t, n.replace("x", "X"), m


def stage_from_text(text: str, edition: int = 9) -> StageResult | None:
    parsed = parse_tnm(text)
    if parsed is None:
        return None
    t, n, m = parsed
    if edition == 9 and n == "N2":
        n = "N2a"  # Conservative: single station unless stated, and flagged below.
        result = stage(t, n, m if m != "M1c" else "M1c1", 9)
        return replace(result, notes=[*result.notes, "N2 was not subclassified; assumed N2a (single station). Confirm the number of stations."])
    if edition == 9 and m == "M1c":
        m = "M1c1"
        result = stage(t, n, m, 9)
        return replace(result, notes=[*result.notes, "M1c was not subclassified; IVB applies to both M1c1 and M1c2."])
    return stage(t, n, m, edition)
