import math

import pytest

from carina.clinical import dosing


def test_mosteller_bsa():
    result = dosing.body_surface_area(175, 70)
    assert result.value == pytest.approx(math.sqrt(175 * 70 / 3600), abs=0.01)
    assert result.unit == "m2"


def test_cockcroft_gault_si_units():
    result = dosing.creatinine_clearance(68, 72, 96, "male")
    assert result.value == pytest.approx((140 - 68) * 72 * 1.23 / 96, abs=0.1)
    female = dosing.creatinine_clearance(68, 72, 96, "female")
    assert female.value < result.value


def test_calvert_formula():
    result = dosing.carboplatin_calvert(5, 80)
    assert result.value == 5 * (80 + 25)


def test_calvert_caps_gfr_at_125():
    result = dosing.carboplatin_calvert(6, 160)
    assert result.value == 6 * (125 + 25)
    assert any("capped" in w for w in result.warnings)


def test_calvert_warns_on_estimated_gfr():
    assert any("measured GFR" in w for w in dosing.carboplatin_calvert(5, 90).warnings)
    assert not any("measured GFR" in w for w in dosing.carboplatin_calvert(5, 90, gfr_source="measured").warnings)


def test_chain_from_patient():
    crcl, dose = dosing.carboplatin_from_patient(5, 68, 72, 96, "male")
    assert dose.value == round(5 * (crcl.value + 25))


@pytest.mark.parametrize(
    "call",
    [
        lambda: dosing.carboplatin_calvert(9, 80),
        lambda: dosing.body_surface_area(50, 70),
        lambda: dosing.creatinine_clearance(12, 40, 60, "male"),
        lambda: dosing.creatinine_clearance(60, 70, 90, "unknown"),
    ],
)
def test_implausible_inputs_rejected(call):
    with pytest.raises(dosing.DosingError):
        call()


def test_performance_status_mapping():
    assert dosing.performance_status_mapping(ecog=1)["karnofsky_range"] == [70, 80]
    assert dosing.performance_status_mapping(karnofsky=60)["ecog"] == 2
