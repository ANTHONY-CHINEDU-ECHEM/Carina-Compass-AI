import asyncio

import pytest

from carina.generation import citations, faithfulness
from carina.generation.extractive import ExtractiveGenerator
from carina.generation.prompts import SYSTEM_PROMPT, build_user_prompt
from carina.llm.base import GenerationRequest, GenerationResult, ProviderError
from carina.llm.router import CircuitBreaker, ProviderRouter

SOURCES = {
    1: "Median progression free survival was 18.9 months with osimertinib and 10.2 months with comparator (hazard ratio 0.46).",
    2: "NICE recommends osimertinib for untreated EGFR mutation positive NSCLC.",
}


def test_invalid_citations_stripped_and_coverage_measured():
    answer = "Osimertinib gave median progression free survival of 18.9 months [1][7]. NICE recommends osimertinib for untreated disease [2]."
    report = citations.validate(answer, SOURCES)
    assert report.invalid_ids == [7]
    assert "[7]" not in report.text
    assert report.coverage == 1.0
    assert report.figures_ok


def test_unsupported_figure_flagged():
    answer = "Median progression free survival was 24.5 months with osimertinib in the trial [1]."
    report = citations.validate(answer, SOURCES)
    assert "24.5 months" in report.unsupported_figures
    assert "Figure check" in citations.flag_unsupported(report.text, report.unsupported_figures)


def test_numeric_equivalence_in_figure_check():
    report = citations.validate("The hazard ratio was 0.460 for progression in the trial [1].", SOURCES)
    assert report.figures_ok


def test_faithfulness_catches_embellished_claim():
    supported = faithfulness.assess("NICE recommends osimertinib for untreated EGFR mutation positive NSCLC [2].", SOURCES)
    assert supported.claim_support == 1.0
    embellished = faithfulness.assess("NICE recommends lorlatinib for ALK positive disease after osimertinib failure [2].", SOURCES)
    assert embellished.claim_support == 0.0


def test_prompt_marks_sources_as_data(container):
    result = container.retriever.retrieve("osimertinib adjuvant")
    prompt = build_user_prompt("question", result.results[:2])
    assert prompt.startswith("<sources>")
    assert "untrusted" in SYSTEM_PROMPT


def test_extractive_generator_cites_every_sentence():
    gen = ExtractiveGenerator()
    text = gen.compose("osimertinib progression free survival", list(SOURCES.items()))
    body = text.split("\n\n")[0]
    report = citations.validate(body, SOURCES)
    assert report.coverage == 1.0 and report.figures_ok


class Failing:
    name = "failing"
    model = "x"

    def available(self):
        return True

    async def generate(self, request):
        raise ProviderError("down")

    async def stream(self, request):
        raise ProviderError("down")
        yield ""  # pragma: no cover


def test_router_falls_back_and_opens_circuit():
    router = ProviderRouter({"failing": Failing(), "extractive": ExtractiveGenerator()}, ["failing"], failure_threshold=2, reset_s=60)
    request = GenerationRequest(system="s", user="u", passages=list(SOURCES.items()), query="osimertinib survival")
    for _ in range(2):
        result, skipped = asyncio.run(router.generate(request))
        assert isinstance(result, GenerationResult) and result.provider == "extractive"
        assert skipped == ["failing"]
    assert router.breakers["failing"].state == "open"


def test_router_stream_falls_back_before_first_token():
    router = ProviderRouter({"failing": Failing(), "extractive": ExtractiveGenerator()}, ["failing"])
    request = GenerationRequest(system="s", user="u", passages=list(SOURCES.items()), query="osimertinib survival")

    async def collect():
        routed, iterator = await router.stream(request)
        return routed, "".join([piece async for piece in iterator])

    routed, text = asyncio.run(collect())
    assert routed.provider == "extractive" and "[1]" in text


def test_circuit_breaker_half_opens():
    breaker = CircuitBreaker(failure_threshold=1, reset_s=0)
    breaker.record_failure()
    assert breaker.state == "half_open"


@pytest.mark.parametrize("question", ["What dose of lurbinectedin for relapsed SCLC?", "zorbatinib results in ZENITH trial"])
def test_answerability_gate_abstains(container, question):
    prepared = container.pipeline.prepare(question)
    assert prepared.answerable is not None and not prepared.answerable.answerable
