import json

import pytest


def test_health_and_ready(client):
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["index"]["chunks"] > 50
    assert any(p["provider"] == "extractive" for p in health["providers"])
    assert client.get("/ready").json()["ready"] is True


def test_ask(client):
    response = client.post("/v1/ask", json={"question": "What did ALINA show for 2 year disease free survival?"})
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "answered"
    assert "93.8%" in body["answer"]


def test_ask_stream_is_server_sent_events(client):
    with client.stream("POST", "/v1/ask/stream", json={"question": "KRAS G12C NSCLC progressed after chemotherapy: options?"}) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = "".join(response.iter_text())
    events = [line.split(": ", 1)[1] for line in payload.splitlines() if line.startswith("event: ")]
    assert events[0] == "meta" and events[-1] == "final"
    assert "tools" in events and "sources" in events and "token" in events


def test_understand(client):
    body = client.post("/v1/understand", json={"question": "Tagrisso after resection of stage IIIA L858R adenocarcinoma"}).json()
    assert "osimertinib" in body["understanding"]["drugs"]
    assert body["understanding"]["setting"] == "adjuvant"


def test_search_with_filters(client):
    body = client.post("/v1/search", json={"query": "durvalumab", "min_evidence_grade": 7, "top_k": 5}).json()
    assert body["results"] and all(r["evidence_grade"] == 7 for r in body["results"])


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({"tnm": "cT2a N2b M0"}, "IIIB"), ({"size_mm": 25, "n": "N1"}, "IIA"), ({"t": "T3", "n": "N2a", "edition": 9}, "IIIA")],
)
def test_stage_tool(client, payload, expected):
    assert client.post("/v1/tools/stage", json=payload).json()["stage_group"] == expected


def test_stage_tool_validation(client):
    assert client.post("/v1/tools/stage", json={"t": "T9", "n": "N0"}).status_code == 422


def test_therapy_trials_screen_and_dose_tools(client):
    ctx = {"histology": "adenocarcinoma", "stage_group": "IV", "biomarkers": ["KRAS_G12C"], "prior_treatments": ["pembrolizumab"], "age": 64}
    therapy = client.post("/v1/tools/therapy", json={"patient_context": ctx}).json()
    assert any(o["nice_reference"] == "TA781" for o in therapy["options"])
    trials = client.post("/v1/tools/trials", json={"patient_context": ctx}).json()
    assert trials["matches"] and all("KRAS" in m["title"] or "G12C" in m["title"] for m in trials["matches"][:3])
    screen = client.post("/v1/tools/screen", json={"planned": ["lorlatinib"], "patient_context": {"current_medicines": ["rifampicin"]}}).json()
    assert screen["highest_severity"] == "contraindicated"
    dose = client.post("/v1/tools/carboplatin", json={"target_auc": 5, "gfr_ml_min": 90}).json()
    assert dose["steps"][0]["value"] == 575
    assert client.post("/v1/tools/carboplatin", json={"target_auc": 5}).status_code == 422
    assert client.post("/v1/tools/bsa", json={"height_cm": 170, "weight_kg": 70}).json()["value"] == pytest.approx(1.82, abs=0.01)


def test_feedback_and_governance(client):
    asked = client.post("/v1/ask", json={"question": "Is capmatinib available on the NHS for MET exon 14 skipping NSCLC?"}).json()
    stored = client.post("/v1/feedback", json={"request_id": asked["request_id"], "rating": "helpful", "comment": "Seen with Mrs Jones"}).json()
    assert stored["stored"] is True
    summary = client.get("/v1/audit/summary").json()
    assert summary["questions"] >= 1
    assert summary["feedback"]["count"] >= 1


def test_knowledge_manifest(client):
    body = client.get("/v1/knowledge").json()
    files = {r["file"] for r in body["rule_sets"]}
    assert {"therapy_matrix.yaml", "safety_rules.yaml", "emergencies.yaml", "supersession.yaml", "lexicon.yaml"} == files
    assert body["index"]["documents"] >= 80


def test_api_key_enforced_when_configured(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "api_keys", ["secret-key"])
    assert client.post("/v1/tools/stage", json={"tnm": "T1a N0 M0"}).status_code == 401
    ok = client.post("/v1/tools/stage", json={"tnm": "T1a N0 M0"}, headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 200


def test_metrics_exposed(client):
    text = client.get("/metrics").text
    assert "carina_answers_total" in text


def test_openapi_lists_every_route(client):
    paths = json.loads(client.get("/openapi.json").text)["paths"]
    for route in ("/v1/ask", "/v1/ask/stream", "/v1/tools/therapy", "/v1/tools/trials", "/v1/audit/summary"):
        assert route in paths
