import asyncio

import yaml

from evaluation import harness


def test_offline_evaluation_passes_the_gate():
    result = asyncio.run(harness.run("offline"))
    thresholds = yaml.safe_load(harness.THRESHOLDS.read_text())
    assert harness.check_gate(result["summary"], thresholds) == []


def test_golden_set_is_well_formed():
    items = harness.load_golden()
    assert len(items) >= 40
    assert len({i["id"] for i in items}) == len(items)
    for item in items:
        assert item["expected_status"] in ("answered", "abstained", "out_of_scope", "any")
