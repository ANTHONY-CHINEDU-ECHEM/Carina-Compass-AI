from carina.clinical.safety_screen import screen
from carina.domain import PatientContext


def rule_ids(result):
    return [f.rule_id for f in result.flags]


def test_lorlatinib_with_rifampicin_is_contraindicated_and_first():
    result = screen(["lorlatinib"], PatientContext(current_medicines=["Rifampicin"]))
    assert result.flags[0].rule_id == "lorlatinib_strong_inducer"
    assert result.flags[0].severity == "contraindicated"


def test_brand_names_are_screened():
    result = screen(["Tarceva"], PatientContext(current_medicines=["omeprazole"]))
    assert "acid_reducer_absorption" in rule_ids(result)


def test_pemetrexed_renal_threshold():
    ctx = PatientContext(age=80, weight_kg=55, serum_creatinine_umol_l=130, sex="female")
    result = screen(["pemetrexed"], ctx)
    assert result.crcl_ml_min is not None and result.crcl_ml_min < 45
    assert "pemetrexed_low_crcl" in rule_ids(result)
    assert "pemetrexed_vitamin_supplementation" in rule_ids(result)


def test_checkpoint_inhibitor_and_transplant():
    result = screen(["pembrolizumab"], PatientContext(conditions=["renal transplant"]))
    assert "checkpoint_transplant" in rule_ids(result)


def test_whole_word_matching_avoids_false_positives():
    result = screen(["osimertinib"], PatientContext(conditions=["mild asthma"]))
    assert "ild_history_tki_adc" not in rule_ids(result)
    result = screen(["osimertinib"], PatientContext(conditions=["ILD"]))
    assert "ild_history_tki_adc" in rule_ids(result)


def test_unknown_medicines_are_reported():
    result = screen(["carboplatin"], PatientContext(current_medicines=["madeupazole"]))
    assert "madeupazole" in result.unknown_medicines
