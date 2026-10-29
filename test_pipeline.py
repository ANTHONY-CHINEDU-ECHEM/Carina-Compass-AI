import asyncio
import json

from carina.domain import PatientContext


def ask(container, question, **kwargs):
    return asyncio.run(container.pipeline.ask(question, **kwargs))


def test_grounded_cited_answer(container):
    result = ask(container, "What did the FLAURA trial show for osimertinib?")
    assert result.status == "answered"
    assert result.grounded
    assert "18.9 months" in result.answer
    assert result.citation_report["coverage"] == 1.0
    assert result.sources and all(s["url"].startswith("https://") for s in result.sources)


def test_therapy_tool_card_runs_with_answer(container):
    result = ask(container, "First line options for stage IVA adenocarcinoma with EGFR exon 19 deletion, PS 1?")
    card = next(t for t in result.tools if t["tool"] == "therapy_options")
    assert card["result"]["options"][0]["nice_reference"] == "TA654"


def test_patient_context_drives_tools(container):
    ctx = PatientContext(histology="squamous", stage_group="IV", pdl1_tps=20, performance_status=1)
    result = ask(container, "What are the first line options?", context=ctx)
    card = next(t for t in result.tools if t["tool"] == "therapy_options")
    references = [o["nice_reference"] for o in card["result"]["options"]]
    assert "TA770" in references and "TA531" not in references


def test_out_of_scope_declined_without_model(container):
    result = ask(container, "How do I renew my car insurance?")
    assert result.status == "out_of_scope"
    assert result.provider is None


def test_emergency_banner_even_when_evidence_is_thin(container):
    result = ask(container, "Patient on pembrolizumab now has severe diarrhoea and abdominal pain")
    assert result.emergencies[0]["category"] == "immune_toxicity"


def test_stream_event_order(container):
    async def collect():
        return [
            event
            async for event in container.pipeline.stream(
                "Day 9 after carboplatin and pemetrexed with temperature 38.5 and rigors; also what does NICE CG151 advise?"
            )
        ]

    events = asyncio.run(collect())
    names = [e["event"] for e in events]
    assert names[0] == "meta"
    assert names[1] == "emergency"
    assert names[-1] == "final"


def test_identifiers_never_reach_the_audit_log(container, audit_path):
    ask(container, "Mr John Smith NHS number 943 476 5919, KRAS G12C NSCLC after chemotherapy: options?")
    text = audit_path.read_text()
    assert "Smith" not in text and "9434765919" not in text and "943 476 5919" not in text
    last = json.loads(text.strip().splitlines()[-1])
    assert last["redactions"]["NHS_NUMBER"] == 1


def test_cache_serves_repeat_question(container):
    first = ask(container, "Is pralsetinib recommended for RET fusion positive NSCLC in England?")
    second = ask(container, "Is pralsetinib recommended for RET fusion positive NSCLC in England?")
    assert not first.cached and second.cached
    assert first.answer == second.answer


def test_superseded_guidance_labelled_in_sources(container):
    result = ask(container, "Is NICE CG121 still the current lung cancer guideline?")
    flagged = [s for s in result.sources if s["superseded_by"]]
    assert flagged and flagged[0]["superseded_by"] == "NG122"
