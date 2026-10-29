"""Clinical query understanding for thoracic oncology.

Turns the way clinicians write ("Tagrisso", "ex19del", "PD-L1 TPS 60%",
"PS1", "cT2a N2b M0") into canonical terms and structured entities before
retrieval. The entities drive the deterministic tools and the retrieval boost
for passages that mention the same biomarker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from carina.clinical.staging import parse_tnm
from carina.domain import PatientContext
from carina.knowledge import load

# Biomarker detection. Order matters: specific EGFR variants before generic EGFR.
POSITIVE = r"[\s-]?(\+|pos\w*|fusion\w*|rearrange\w*|mut\w*|altered|alteration|driven|amplif\w*)"
BIOMARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EGFR_T790M", re.compile(r"\bt790m\b", re.I)),
    ("EGFR_EXON20_INS", re.compile(r"\b(exon\s?20\s?(ins\w*|insertion)|ex20ins)\b", re.I)),
    ("EGFR_COMMON", re.compile(r"\b(exon\s?19\s?(del\w*)?|ex19del|del19|19del|l858r|exon\s?21)\b", re.I)),
    ("EGFR_COMMON", re.compile(r"\begfr(?:[\s-]?tk)?" + POSITIVE + r"|\begfr[\s-]?m\b|\begfr[\s-]?(sensitising|sensitizing)", re.I)),
    ("ALK", re.compile(r"\balk" + POSITIVE, re.I)),
    ("ROS1", re.compile(r"\bros\s?1" + POSITIVE, re.I)),
    ("KRAS_G12C", re.compile(r"\b(kras[\s-]?)?g12c\b", re.I)),
    ("BRAF_V600", re.compile(r"\b(braf[\s-]?)?v600e?\b", re.I)),
    ("MET_EX14", re.compile(r"\b(met[\s-]?(ex|exon)\s?14|metex14)", re.I)),
    ("RET", re.compile(r"\bret" + POSITIVE, re.I)),
    ("NTRK", re.compile(r"\bntrk\s?\d?" + POSITIVE, re.I)),
    ("HER2_MUT", re.compile(r"\b(her2|erbb2)[\s-]?(mut\w*|exon\s?20)", re.I)),
]

NEGATION_BEFORE = re.compile(r"\b(no|without|negative for|not|absence of|excluding|wild[\s-]?type)\b[^.;]{0,30}$", re.I)
NEGATION_AFTER = re.compile(r"^[^.;]{0,12}\b(negative|wild[\s-]?type|wt|not detected)\b", re.I)


def detect_biomarkers(text: str) -> list[str]:
    """Biomarker codes mentioned positively in text.

    Negated mentions ("no EGFR or ALK alteration", "ALK negative",
    "EGFR wild type") are ignored, so a passage about driver negative disease
    is not tagged with the drivers it excludes.
    """
    found: list[str] = []
    for code, pattern in BIOMARKER_PATTERNS:
        if code in found:
            continue
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 40) : match.start()]
            after = text[match.end() : match.end() + 20]
            if NEGATION_BEFORE.search(before) or NEGATION_AFTER.search(after):
                continue
            found.append(code)
            break
    if "EGFR_COMMON" in found and any(c in found for c in ("EGFR_T790M", "EGFR_EXON20_INS")):
        if not re.search(r"exon\s?19|ex19del|l858r|del19|19del|exon\s?21", text, re.I):
            found.remove("EGFR_COMMON")
    return found


HISTOLOGY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("small_cell", re.compile(r"\b(small[\s-]?cell|sclc|oat cell)\b", re.I)),
    ("squamous", re.compile(r"\b(?<!non[\s-])(squamous|lusc)\b", re.I)),
    ("non_squamous", re.compile(r"\bnon[\s-]?squamous\b", re.I)),
    ("adenocarcinoma", re.compile(r"\b(adenocarcinoma|adeno|luad)\b", re.I)),
    ("large_cell", re.compile(r"\blarge[\s-]?cell\b", re.I)),
    ("nsclc", re.compile(r"\b(nsclc|non[\s-]?small[\s-]?cell)\b", re.I)),
    ("mesothelioma", re.compile(r"\bmesothelioma\b", re.I)),
]

PDL1_PATTERN = re.compile(
    r"\b(?:pd[\s-]?l1|tps|tumou?r proportion score)\b[^0-9<>≥≤]{0,20}(?P<op>≥|>=|>|<|≤|<=|of|at|is|=)?\s*(?P<value>\d{1,3}(?:\.\d+)?)\s*%",
    re.I,
)
PDL1_HIGH_WORDS = re.compile(r"\b(pd[\s-]?l1|tps)\s?(high|strongly positive)\b", re.I)
PS_PATTERN = re.compile(r"\b(?:ecog|who|performance status|ps)\s?(?:ps)?\s?(?:of|=|is)?\s?([0-4])\b", re.I)
AGE_PATTERN = re.compile(r"\b(\d{2,3})\s?(?:y/?o|yo|years? old|year old|yrs?|year[\s-]old)\b|\baged?\s(\d{2,3})\b", re.I)
WEIGHT_PATTERN = re.compile(r"\b(\d{2,3}(?:\.\d)?)\s?kg\b", re.I)
HEIGHT_PATTERN = re.compile(r"\b(1\d{2}(?:\.\d)?)\s?cm\b", re.I)
CREATININE_PATTERN = re.compile(r"\b(?:creatinine|creat|cr)\s?(?:of|=|is)?\s?(\d{2,4})\s?(?:umol|µmol|micromol)", re.I)
AUC_PATTERN = re.compile(r"\bauc\s?(?:of|=)?\s?(\d(?:\.\d)?)\b", re.I)
STAGE_PATTERN = re.compile(r"\bstage\s?(i{1,3}v?|iv|[1-4])\s?([abc]\d?)?\b", re.I)
SEX_PATTERN = re.compile(r"\b(male|female|man|woman)\b", re.I)

INTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "staging": re.compile(r"\b(stage|staging|tnm|upstag\w*|downstag\w*)\b", re.I),
    "treatment_options": re.compile(
        r"\b(option|options|treat\w*|therapy|regimen|first[\s-]?line|second[\s-]?line|next line|offer|recommend\w*|eligible|adjuvant|neoadjuvant|perioperative|maintenance|consolidation)\b",
        re.I,
    ),
    "trials": re.compile(r"\b(trials|recruiting|enrol\w*|trial options|studies to join|nct\d{8})\b", re.I),
    "dosing": re.compile(r"\b(dose|dosing|calvert|auc|bsa|body surface area|creatinine clearance|cockcroft|mg/m2)\b", re.I),
    "interactions": re.compile(r"\b(interact\w*|together with|co[\s-]?prescrib\w*|safe to (take|give|use)|contraindicat\w*|caution)\b", re.I),
    "toxicity": re.compile(r"\b(toxicit\w*|side effects?|adverse|pneumonitis|colitis|hepatitis|rash|diarrh\w*|ild)\b", re.I),
    "evidence": re.compile(r"\b(evidence|trial results?|survival|pfs|os|hazard ratio|efficacy)\b", re.I),
    "performance_status": re.compile(r"\b(karnofsky|ecog|performance status)\b.{0,40}\b(convert|equivalent|mapping|map)\b", re.I),
}

SETTING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("neoadjuvant", re.compile(r"\b(neo[\s-]?adjuvant|before surgery|pre[\s-]?operative)\b", re.I)),
    ("perioperative", re.compile(r"\bperi[\s-]?operative\b", re.I)),
    ("adjuvant", re.compile(r"\b(adjuvant|after (complete )?resection|resected|post[\s-]?operative)\b", re.I)),
    ("consolidation_after_crt", re.compile(r"\b(after|following) (concurrent )?(chemoradio\w*|crt)\b|\bconsolidation\b", re.I)),
    ("unresectable_stage3", re.compile(r"\bunresectable\b", re.I)),
    ("extensive_stage_sclc", re.compile(r"\b(extensive[\s-]?stage|es[\s-]?sclc)\b", re.I)),
    ("limited_stage_sclc", re.compile(r"\b(limited[\s-]?stage|ls[\s-]?sclc)\b", re.I)),
    ("relapsed_sclc", re.compile(r"\b(relapsed|recurrent|refractory)\b.{0,30}\b(sclc|small cell)\b", re.I)),
    (
        "advanced_subsequent",
        re.compile(
            r"\b(second[\s-]?line|third[\s-]?line|after progression|progressed on|progression on|progressed after|previously treated|after (?:platinum[\s-]based )?chemotherapy\b|after (osimertinib|alectinib|lorlatinib|immunotherapy|chemo[\s-]?immunotherapy|an? (egfr|alk) (tki|inhibitor|tyrosine kinase inhibitor))|subsequent line|later line)",
            re.I,
        ),
    ),
    ("advanced_first_line", re.compile(r"\b(first[\s-]?line|untreated|treatment[\s-]?naive|newly diagnosed (metastatic|advanced|stage iv))\b", re.I)),
]


@dataclass
class QueryUnderstanding:
    original: str
    normalised: str
    expansions: list[str] = field(default_factory=list)
    drugs: list[str] = field(default_factory=list)
    biomarkers: list[str] = field(default_factory=list)
    histology: str | None = None
    pdl1_tps: float | None = None
    pdl1_operator: str | None = None
    performance_status: int | None = None
    age: int | None = None
    sex: str | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    creatinine_umol_l: float | None = None
    target_auc: float | None = None
    tnm: tuple[str, str, str] | None = None
    stage_group: str | None = None
    setting: str | None = None
    intents: list[str] = field(default_factory=list)

    def retrieval_query(self) -> str:
        parts = [self.normalised]
        parts.extend(self.expansions)
        parts.extend(self.drugs)
        parts.extend(_biomarker_terms(code) for code in self.biomarkers)
        return " ".join(part for part in parts if part)

    def precision_query(self) -> str:
        """The question with canonical drug and biomarker terms, without synonym expansions."""
        parts = [self.normalised, *self.drugs, *(code.split("_")[0].lower() for code in self.biomarkers)]
        return " ".join(part for part in parts if part)

    def to_patient_context(self, base: PatientContext | None = None) -> PatientContext:
        ctx = base.model_copy() if base else PatientContext()
        ctx.histology = ctx.histology or self.histology
        ctx.biomarkers = sorted(set(ctx.biomarkers) | set(self.biomarkers))
        ctx.pdl1_tps = ctx.pdl1_tps if ctx.pdl1_tps is not None else self.pdl1_tps
        ctx.performance_status = ctx.performance_status if ctx.performance_status is not None else self.performance_status
        ctx.age = ctx.age or (self.age if self.age and 18 <= self.age <= 110 else None)
        ctx.sex = ctx.sex or self.sex
        ctx.weight_kg = ctx.weight_kg or self.weight_kg
        ctx.height_cm = ctx.height_cm or self.height_cm
        ctx.serum_creatinine_umol_l = ctx.serum_creatinine_umol_l or self.creatinine_umol_l
        ctx.setting = ctx.setting or self.setting
        ctx.stage_group = ctx.stage_group or self.stage_group
        if self.tnm and not ctx.t_category:
            ctx.t_category, ctx.n_category, ctx.m_category = self.tnm
        return ctx

    def as_dict(self) -> dict[str, object]:
        return {
            "normalised": self.normalised,
            "drugs": self.drugs,
            "biomarkers": self.biomarkers,
            "histology": self.histology,
            "pdl1_tps": self.pdl1_tps,
            "pdl1_operator": self.pdl1_operator,
            "performance_status": self.performance_status,
            "age": self.age,
            "sex": self.sex,
            "weight_kg": self.weight_kg,
            "height_cm": self.height_cm,
            "creatinine_umol_l": self.creatinine_umol_l,
            "target_auc": self.target_auc,
            "tnm": list(self.tnm) if self.tnm else None,
            "stage_group": self.stage_group,
            "setting": self.setting,
            "intents": self.intents,
        }


def _biomarker_terms(code: str) -> str:
    return {
        "EGFR_COMMON": "EGFR mutation exon 19 deletion L858R",
        "EGFR_T790M": "EGFR T790M",
        "EGFR_EXON20_INS": "EGFR exon 20 insertion",
        "ALK": "ALK positive",
        "ROS1": "ROS1 positive",
        "KRAS_G12C": "KRAS G12C",
        "BRAF_V600": "BRAF V600",
        "MET_EX14": "MET exon 14 skipping",
        "RET": "RET fusion",
        "NTRK": "NTRK fusion",
        "HER2_MUT": "HER2 mutation",
    }.get(code, code)


@lru_cache(maxsize=1)
def _lexicon() -> dict[str, Any]:
    return load("lexicon.yaml")


@lru_cache(maxsize=1)
def _known_drugs() -> frozenset[str]:
    lex = _lexicon()
    drugs: set[str] = set(lex["brand_to_generic"].values())
    for members in lex["drug_classes"].values():
        drugs.update(members)
    return frozenset(drugs)


def drug_class_members(name: str) -> list[str]:
    return list(_lexicon()["drug_classes"].get(name, []))


def classes_of(drug: str) -> list[str]:
    drug = drug.lower()
    return [cls for cls, members in _lexicon()["drug_classes"].items() if drug in members]


def canonical_drug(token: str) -> str | None:
    token = token.lower().strip()
    lex = _lexicon()
    brand = lex["brand_to_generic"].get(token)
    if brand:
        return brand
    if token in _known_drugs():
        return token
    return None


def normalise_text(text: str) -> tuple[str, list[str]]:
    """Lower case, map US spellings, brands and abbreviations; return expansions."""
    lex = _lexicon()
    lowered = text.lower()
    expansions: list[str] = []
    for us, uk in lex["us_to_uk_spelling"].items():
        lowered = re.sub(rf"\b{re.escape(us)}\b", uk, lowered)
    for brand, generic in lex["brand_to_generic"].items():
        if re.search(rf"\b{re.escape(brand)}\b", lowered):
            lowered = re.sub(rf"\b{re.escape(brand)}\b", generic, lowered)
    for abbreviation, expansion in lex["abbreviations"].items():
        if re.search(rf"(?<![\w-]){re.escape(abbreviation)}(?![\w-])", lowered):
            expansions.append(expansion)
    lowered = re.sub(r"pd[\s-]l1", "pd-l1", lowered)
    for phrase, alternatives in lex.get("synonyms", {}).items():
        if re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", lowered):
            expansions.extend(alternatives)
    return lowered, list(dict.fromkeys(expansions))


def find_drugs(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    candidates = set(_known_drugs()) | set(_lexicon()["brand_to_generic"].keys())
    for candidate in sorted(candidates, key=len, reverse=True):
        if re.search(rf"\b{re.escape(candidate)}\b", lowered):
            canonical = canonical_drug(candidate) or candidate
            if canonical not in found:
                found.append(canonical)
    return found


def understand(question: str) -> QueryUnderstanding:
    normalised, expansions = normalise_text(question)
    result = QueryUnderstanding(original=question, normalised=normalised, expansions=expansions)
    result.drugs = find_drugs(normalised)

    result.biomarkers = detect_biomarkers(normalised)

    histology_text = re.sub(r"non[\s-]?small[\s-]?cell", " nsclc ", normalised)
    for code, pattern in HISTOLOGY_PATTERNS:
        if pattern.search(histology_text):
            result.histology = code
            break

    match = PDL1_PATTERN.search(normalised)
    if match:
        result.pdl1_tps = float(match.group("value"))
        operator = match.group("op")
        result.pdl1_operator = {">=": "≥", "<=": "≤"}.get(operator or "", operator if operator in ("≥", ">", "<", "≤") else "=")
    elif PDL1_HIGH_WORDS.search(normalised):
        result.pdl1_tps = 50.0
        result.pdl1_operator = "≥"

    ps = PS_PATTERN.search(normalised)
    if ps:
        result.performance_status = int(ps.group(1))
    age = AGE_PATTERN.search(normalised)
    if age:
        value = int(age.group(1) or age.group(2))
        result.age = value if 0 < value < 120 else None
    weight = WEIGHT_PATTERN.search(normalised)
    if weight:
        result.weight_kg = float(weight.group(1))
    height = HEIGHT_PATTERN.search(normalised)
    if height:
        result.height_cm = float(height.group(1))
    creatinine = CREATININE_PATTERN.search(normalised)
    if creatinine:
        result.creatinine_umol_l = float(creatinine.group(1))
    auc = AUC_PATTERN.search(normalised)
    if auc:
        result.target_auc = float(auc.group(1))
    sex = SEX_PATTERN.search(normalised)
    if sex:
        result.sex = "male" if sex.group(1).lower() in ("male", "man") else "female"

    result.tnm = parse_tnm(question)
    stage_match = STAGE_PATTERN.search(normalised)
    if stage_match:
        result.stage_group = _canonical_stage(stage_match.group(1), stage_match.group(2))

    for setting, pattern in SETTING_PATTERNS:
        if pattern.search(normalised):
            result.setting = setting
            break
    if result.setting is None and result.stage_group and result.stage_group.startswith("IV"):
        result.setting = "advanced_first_line"

    for intent, pattern in INTENT_PATTERNS.items():
        if pattern.search(normalised):
            result.intents.append(intent)
    if result.biomarkers and "treatment_options" not in result.intents and not result.intents:
        result.intents.append("treatment_options")
    return result


_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV"}


def _canonical_stage(number: str, suffix: str | None) -> str:
    roman = _ROMAN.get(number, number.upper())
    return roman + (suffix.upper() if suffix else "")
