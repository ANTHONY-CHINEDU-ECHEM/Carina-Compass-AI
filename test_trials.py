from carina.clinical.trials import match_trials
from carina.domain import PatientContext

TRIALS = [
    {
        "nct_id": "NCT00000001",
        "title": "KRAS G12C first line",
        "overall_status": "RECRUITING",
        "status_verified": True,
        "phases": ["PHASE3"],
        "biomarkers": ["KRAS_G12C"],
        "histology": ["nsclc"],
        "settings": ["advanced_first_line"],
        "countries": ["United Kingdom", "Spain"],
        "uk_sites": ["The Christie, Manchester"],
        "minimum_age": "18 Years",
        "sex": "ALL",
    },
    {
        "nct_id": "NCT00000002",
        "title": "EGFR trial",
        "overall_status": "RECRUITING",
        "status_verified": True,
        "phases": ["PHASE3"],
        "biomarkers": ["EGFR_COMMON"],
        "histology": ["nsclc"],
        "countries": ["United States"],
    },
    {
        "nct_id": "NCT00000003",
        "title": "Completed KRAS trial",
        "overall_status": "COMPLETED",
        "status_verified": True,
        "phases": ["PHASE2"],
        "biomarkers": ["KRAS_G12C"],
        "histology": ["nsclc"],
        "countries": ["United Kingdom"],
    },
    {
        "nct_id": "NCT00000004",
        "title": "SCLC trial",
        "overall_status": "RECRUITING",
        "status_verified": True,
        "phases": ["PHASE3"],
        "biomarkers": [],
        "histology": ["small_cell"],
        "countries": ["United Kingdom"],
    },
    {
        "nct_id": "NCT00000005",
        "title": "Paediatric only",
        "overall_status": "RECRUITING",
        "status_verified": True,
        "phases": ["PHASE1"],
        "biomarkers": ["KRAS_G12C"],
        "histology": ["nsclc"],
        "maximum_age": "17 Years",
    },
]


def test_biomarker_histology_and_status_filters():
    result = match_trials(PatientContext(histology="adenocarcinoma", biomarkers=["KRAS_G12C"], age=64), TRIALS)
    ncts = [m["nct_id"] for m in result["matches"]]
    assert ncts[0] == "NCT00000001"
    assert "NCT00000002" not in ncts  # different driver
    assert "NCT00000003" not in ncts  # closed
    assert "NCT00000004" not in ncts  # small cell
    assert "NCT00000005" not in ncts  # age limit


def test_unverified_status_is_kept_with_a_caution():
    trials = [
        {
            "nct_id": "NCT00000009",
            "title": "Seed record",
            "overall_status": "NOT_VERIFIED",
            "status_verified": False,
            "phases": ["PHASE3"],
            "biomarkers": ["KRAS_G12C"],
        }
    ]
    result = match_trials(PatientContext(biomarkers=["KRAS_G12C"]), trials)
    assert result["matches"][0]["status_verified"] is False
    assert any("not verified" in c for c in result["matches"][0]["cautions"])
