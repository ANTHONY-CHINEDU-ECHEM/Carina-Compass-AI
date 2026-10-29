from carina.clinical.therapy import match_therapies
from carina.domain import PatientContext


def ids(match):
    return [o.option_id for o in match.options]


def test_egfr_first_line_puts_osimertinib_first():
    match = match_therapies(PatientContext(histology="adenocarcinoma", stage_group="IVA", biomarkers=["EGFR_COMMON"], performance_status=1))
    assert match.setting == "advanced_first_line"
    assert match.options[0].option_id == "egfr_osimertinib_first"
    assert match.options[0].nice_reference == "TA654"
    # Immunotherapy first line options are not offered for driver positive disease.
    assert "pdl1_high_pembrolizumab" not in ids(match)


def test_pdl1_high_driver_negative():
    match = match_therapies(PatientContext(histology="adenocarcinoma", stage_group="IVB", biomarkers=[], pdl1_tps=80, performance_status=0))
    assert "pdl1_high_pembrolizumab" in ids(match)
    assert "nonsq_pembrolizumab_pemetrexed_platinum" in ids(match)
    assert "sq_pembrolizumab_carboplatin_paclitaxel" not in ids(match)


def test_pdl1_threshold_excludes_monotherapy_below_50():
    match = match_therapies(PatientContext(histology="squamous", stage_group="IV", pdl1_tps=20))
    assert "pdl1_high_pembrolizumab" not in ids(match)
    assert "sq_pembrolizumab_carboplatin_paclitaxel" in ids(match)


def test_adjuvant_alk():
    match = match_therapies(PatientContext(histology="adenocarcinoma", setting="adjuvant", biomarkers=["ALK"], performance_status=0))
    assert "adjuvant_alectinib" in ids(match)
    assert "adjuvant_immunotherapy" not in ids(match)


def test_not_recommended_options_sorted_last():
    match = match_therapies(PatientContext(histology="adenocarcinoma", stage_group="IV", biomarkers=["RET"], performance_status=1))
    statuses = [o.nice_status for o in match.options]
    assert "not_recommended" in statuses
    assert statuses.index("not_recommended") > statuses.index("see_appraisal")


def test_t790m_requires_prior_egfr_tki():
    with_prior = match_therapies(
        PatientContext(histology="adenocarcinoma", setting="advanced_subsequent", biomarkers=["EGFR_T790M"], prior_treatments=["erlotinib"])
    )
    assert "egfr_t790m_osimertinib" in ids(with_prior)
    wrong_prior = match_therapies(
        PatientContext(histology="adenocarcinoma", setting="advanced_subsequent", biomarkers=["EGFR_T790M"], prior_treatments=["pembrolizumab"])
    )
    assert "egfr_t790m_osimertinib" not in ids(wrong_prior)


def test_extensive_stage_sclc_inferred_and_ps_respected():
    fit = match_therapies(PatientContext(histology="small_cell", stage_group="IV", performance_status=1))
    assert fit.setting == "extensive_stage_sclc"
    assert {"es_sclc_durvalumab", "es_sclc_atezolizumab"} <= set(ids(fit))
    frail = match_therapies(PatientContext(histology="small_cell", stage_group="IV", performance_status=3))
    assert "es_sclc_atezolizumab" not in ids(frail)


def test_missing_information_reported():
    match = match_therapies(PatientContext(stage_group="IV"))
    assert "histology" in match.missing_information
    assert any("molecular" in m for m in match.missing_information)


def test_no_option_ever_contains_a_dose():
    match = match_therapies(PatientContext(histology="adenocarcinoma", stage_group="IV", pdl1_tps=60))
    for option in match.options:
        assert "mg" not in option.regimen.lower()
