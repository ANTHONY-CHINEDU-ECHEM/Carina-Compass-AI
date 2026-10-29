import pytest

from carina.clinical import staging


@pytest.mark.parametrize(
    ("t", "n", "m", "expected"),
    [
        ("T1a", "N0", "M0", "IA1"),
        ("T1b", "N0", "M0", "IA2"),
        ("T1c", "N0", "M0", "IA3"),
        ("T2a", "N0", "M0", "IB"),
        ("T2b", "N0", "M0", "IIA"),
        ("T3", "N0", "M0", "IIB"),
        ("T4", "N0", "M0", "IIIA"),
        ("T1c", "N1", "M0", "IIA"),
        ("T2a", "N1", "M0", "IIB"),
        ("T3", "N1", "M0", "IIIA"),
        ("T4", "N1", "M0", "IIIA"),
        ("T1b", "N2a", "M0", "IIB"),
        ("T2a", "N2a", "M0", "IIIA"),
        ("T3", "N2a", "M0", "IIIA"),
        ("T4", "N2a", "M0", "IIIB"),
        ("T1a", "N2b", "M0", "IIIA"),
        ("T2b", "N2b", "M0", "IIIB"),
        ("T3", "N2b", "M0", "IIIB"),
        ("T4", "N2b", "M0", "IIIB"),
        ("T1a", "N3", "M0", "IIIB"),
        ("T2a", "N3", "M0", "IIIB"),
        ("T3", "N3", "M0", "IIIC"),
        ("T4", "N3", "M0", "IIIC"),
        ("T2a", "N0", "M1a", "IVA"),
        ("T1a", "N0", "M1b", "IVA"),
        ("T3", "N2b", "M1c1", "IVB"),
        ("T1a", "N1", "M1c2", "IVB"),
    ],
)
def test_ninth_edition_stage_groups(t, n, m, expected):
    assert staging.stage(t, n, m, edition=9).stage_group == expected


@pytest.mark.parametrize(
    ("t", "n", "m", "expected"),
    [("T1a", "N1", "M0", "IIB"), ("T1a", "N2", "M0", "IIIA"), ("T3", "N2", "M0", "IIIB"), ("T2a", "N0", "M1c", "IVB")],
)
def test_eighth_edition_stage_groups(t, n, m, expected):
    assert staging.stage(t, n, m, edition=8).stage_group == expected


def test_changed_combinations_are_flagged():
    result = staging.stage("T1c", "N1", "M0", 9)
    assert result.stage_group == "IIA"
    assert any("IIB" in note and "IIA" in note for note in result.notes)


def test_ninth_edition_rejects_unsplit_n2():
    with pytest.raises(staging.StagingError):
        staging.stage("T2a", "N2", "M0", 9)


def test_tis_and_occult():
    assert staging.stage("Tis", "N0", "M0").stage_group == "0"
    assert staging.stage("TX", "N0", "M0").stage_group == "Occult carcinoma"


@pytest.mark.parametrize(
    ("size", "kwargs", "expected"),
    [
        (8, {}, "T1a"),
        (15, {}, "T1b"),
        (25, {}, "T1c"),
        (35, {}, "T2a"),
        (45, {}, "T2b"),
        (60, {}, "T3"),
        (80, {}, "T4"),
        (18, {"visceral_pleura": True}, "T2a"),
        (22, {"chest_wall_or_pericardium": True}, "T3"),
        (25, {"mediastinum_or_great_vessels": True}, "T4"),
        (20, {"invasive_mm": 4}, "T1mi"),
    ],
)
def test_t_from_size(size, kwargs, expected):
    assert staging.t_from_size(size, **kwargs) == expected


def test_parse_tnm_with_prefixes():
    assert staging.parse_tnm("Restaged as cT2a N2b M0 after EBUS") == ("T2a", "N2b", "M0")
    assert staging.parse_tnm("pT1cN1M0") == ("T1c", "N1", "M0")


def test_stage_from_text_assumes_single_station_n2_and_says_so():
    result = staging.stage_from_text("T2a N2 M0", 9)
    assert result is not None
    assert result.n == "N2a"
    assert any("not subclassified" in note for note in result.notes)


def test_resectability_hint_for_metastatic_disease():
    assert "systemic therapy" in staging.stage("T1a", "N0", "M1b").resectability_hint
