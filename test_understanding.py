import pytest

from carina.clinical.understanding import canonical_drug, detect_biomarkers, find_drugs, understand


def test_brand_names_map_to_generics():
    assert canonical_drug("Tagrisso") == "osimertinib"
    assert canonical_drug("keytruda") == "pembrolizumab"
    assert set(find_drugs("on tagrisso, previously had alimta")) == {"osimertinib", "pemetrexed"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EGFR exon 19 deletion", ["EGFR_COMMON"]),
        ("L858R positive adenocarcinoma", ["EGFR_COMMON"]),
        ("acquired T790M after erlotinib", ["EGFR_T790M"]),
        ("EGFR exon 20 insertion", ["EGFR_EXON20_INS"]),
        ("ALK positive", ["ALK"]),
        ("ALK-rearranged NSCLC", ["ALK"]),
        ("KRAS G12C mutated", ["KRAS_G12C"]),
        ("BRAF V600E", ["BRAF_V600"]),
        ("MET exon 14 skipping", ["MET_EX14"]),
        ("RET fusion", ["RET"]),
        ("HER2 mutated", ["HER2_MUT"]),
    ],
)
def test_biomarkers_detected(text, expected):
    assert detect_biomarkers(text.lower()) == expected


@pytest.mark.parametrize("text", ["no EGFR or ALK alteration", "EGFR wild type", "ALK negative on IHC", "without ALK rearrangement"])
def test_negated_biomarkers_ignored(text):
    assert detect_biomarkers(text.lower()) == []


def test_full_question_understanding():
    qu = understand("68 year old man, stage IVA adenocarcinoma, PD-L1 TPS 60%, ECOG 1, EGFR wild type: first line options?")
    assert qu.histology == "adenocarcinoma"
    assert qu.pdl1_tps == 60
    assert qu.performance_status == 1
    assert qu.age == 68
    assert qu.biomarkers == []
    assert qu.stage_group == "IVA"
    assert qu.setting == "advanced_first_line"
    assert "treatment_options" in qu.intents


def test_small_cell_not_confused_with_non_small_cell():
    assert understand("non-small cell lung cancer stage II").histology == "nsclc"
    assert understand("extensive stage small cell lung cancer").histology == "small_cell"


def test_tnm_and_settings():
    qu = understand("cT3 N2a M0 squamous, unresectable")
    assert qu.tnm == ("T3", "N2a", "M0")
    assert qu.histology == "squamous"
    assert qu.setting == "unresectable_stage3"


def test_synonym_expansion():
    qu = understand("first line therapy for metastatic disease")
    assert "untreated" in qu.expansions
    assert "advanced" in qu.expansions
