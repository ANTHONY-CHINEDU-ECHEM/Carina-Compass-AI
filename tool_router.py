"""Decide which deterministic tools a question needs and run them.

Tool results are streamed to the clinician as separate cards before the model
writes anything. They are deliberately kept out of the model prompt so that
the figure check on the generated answer stays honest: a number in the answer
must come from a cited source, not from a tool card the model has copied.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from carina.clinical import dosing, safety_screen, staging, therapy, trials
from carina.clinical.understanding import QueryUnderstanding
from carina.domain import PatientContext


@dataclass
class ToolCard:
    tool: str
    title: str
    status: str  # "ok", "needs_input" or "error"
    result: dict[str, Any] | None = None
    missing: list[str] = field(default_factory=list)
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "title": self.title,
            "status": self.status,
            "result": self.result,
            "missing": self.missing,
            "message": self.message,
        }


def route(
    understanding: QueryUnderstanding,
    ctx: PatientContext,
    trial_source: Callable[[], Iterable[dict[str, Any]]] | None = None,
) -> list[ToolCard]:
    intents = set(understanding.intents)
    cards: list[ToolCard] = []

    # Staging
    tnm = understanding.tnm or ((ctx.t_category, ctx.n_category, ctx.m_category or "M0") if ctx.t_category and ctx.n_category else None)
    if tnm:
        try:
            result = staging.stage_from_text(" ".join(tnm), edition=9)
            if result is not None:
                eighth = None
                try:
                    n8 = "N2" if result.n.startswith("N2") else result.n
                    m8 = "M1c" if result.m.startswith("M1c") else result.m
                    eighth = staging.stage(result.t, n8, m8, edition=8).stage_group
                except staging.StagingError:
                    eighth = None
                payload = result.as_dict() | {"eighth_edition_stage_group": eighth}
                cards.append(ToolCard("staging", "TNM stage group (9th edition)", "ok", payload))
                if not ctx.stage_group:
                    ctx.stage_group = result.stage_group
        except staging.StagingError as exc:
            cards.append(ToolCard("staging", "TNM stage group", "error", message=str(exc)))
    elif "staging" in intents and not understanding.stage_group:
        cards.append(ToolCard("staging", "TNM stage group", "needs_input", missing=["T, N and M categories (for example cT2a N2b M0)"]))

    # Treatment options
    wants_options = "treatment_options" in intents or bool(understanding.biomarkers) or understanding.setting is not None
    if wants_options and (ctx.histology or ctx.biomarkers or ctx.setting or ctx.stage_group):
        match = therapy.match_therapies(ctx)
        if match.options:
            cards.append(ToolCard("therapy_options", "NICE aligned treatment options", "ok", match.as_dict()))
        else:
            cards.append(
                ToolCard(
                    "therapy_options",
                    "NICE aligned treatment options",
                    "needs_input",
                    result=match.as_dict(),
                    missing=match.missing_information,
                    message="No option matched the information given.",
                )
            )

    # Trials
    if "trials" in intents and trial_source is not None:
        found = trials.match_trials(ctx, trial_source())
        cards.append(ToolCard("trial_matching", "Clinical trials to consider", "ok", found))

    # Dosing
    if "dosing" in intents:
        cards.extend(_dosing_cards(understanding, ctx))

    # Safety screen
    planned = understanding.drugs
    has_context = bool(ctx.current_medicines or ctx.conditions or ctx.allergies or ctx.serum_creatinine_umol_l)
    if planned and (has_context or "interactions" in intents):
        screened = safety_screen.screen(planned, ctx)
        cards.append(ToolCard("safety_screen", "Medication safety screen", "ok", screened.as_dict()))

    # Performance status mapping
    if "performance_status" in intents and understanding.performance_status is not None:
        cards.append(ToolCard("performance_status", "ECOG and Karnofsky", "ok", dosing.performance_status_mapping(ecog=understanding.performance_status)))
    return cards


def _dosing_cards(understanding: QueryUnderstanding, ctx: PatientContext) -> list[ToolCard]:
    cards: list[ToolCard] = []
    text = understanding.normalised
    if "carboplatin" in understanding.drugs or "calvert" in text or understanding.target_auc is not None:
        auc = understanding.target_auc
        needed = {
            "target AUC": auc,
            "age": ctx.age,
            "weight (kg)": ctx.weight_kg,
            "serum creatinine (micromol/L)": ctx.serum_creatinine_umol_l,
            "sex": ctx.sex,
        }
        missing = [name for name, value in needed.items() if value in (None, "")]
        if missing:
            cards.append(ToolCard("carboplatin_calvert", "Carboplatin dose check (Calvert)", "needs_input", missing=missing))
        else:
            try:
                steps = dosing.carboplatin_from_patient(auc, ctx.age, ctx.weight_kg, ctx.serum_creatinine_umol_l, ctx.sex)  # type: ignore[arg-type]
                cards.append(ToolCard("carboplatin_calvert", "Carboplatin dose check (Calvert)", "ok", {"steps": [step.as_dict() for step in steps]}))
            except dosing.DosingError as exc:
                cards.append(ToolCard("carboplatin_calvert", "Carboplatin dose check (Calvert)", "error", message=str(exc)))
    if "bsa" in text or "body surface area" in text or "mg/m2" in text:
        if ctx.height_cm and ctx.weight_kg:
            try:
                cards.append(ToolCard("bsa", "Body surface area", "ok", dosing.body_surface_area(ctx.height_cm, ctx.weight_kg).as_dict()))
            except dosing.DosingError as exc:
                cards.append(ToolCard("bsa", "Body surface area", "error", message=str(exc)))
        else:
            cards.append(
                ToolCard(
                    "bsa", "Body surface area", "needs_input", missing=[n for n, v in (("height (cm)", ctx.height_cm), ("weight (kg)", ctx.weight_kg)) if not v]
                )
            )
    return cards
