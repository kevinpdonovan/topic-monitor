from engine.pipeline.items import make_item
from engine.pipeline.score import ai_score, keyword_gate, run_keyword_gate

PROFILE = {
    "keywords": [{"term": "central bank digital currency", "language": "en"}, {"term": "CBDC", "language": "en"}],
    "exclusions": ["video game currency"],
}


def test_keyword_gate_passes_on_match():
    item = make_item(title="A new CBDC pilot launches", source_type="news", connector="test", abstract="")
    gate = keyword_gate(item, PROFILE)
    assert gate["passed"]
    assert "cbdc" in gate["matched_terms"]


def test_keyword_gate_rejects_on_exclusion_even_if_keyword_also_matches():
    item = make_item(title="CBDC-themed video game currency launches", source_type="news", connector="test")
    gate = keyword_gate(item, PROFILE)
    assert not gate["passed"]
    assert "excluded" in gate["reason"]


def test_keyword_gate_rejects_unrelated_item():
    item = make_item(title="A new recipe for sourdough bread", source_type="news", connector="test")
    gate = keyword_gate(item, PROFILE)
    assert not gate["passed"]


def test_run_keyword_gate_splits_survivors_and_rejected():
    items = [
        make_item(title="CBDC pilot expands", source_type="news", connector="test"),
        make_item(title="Unrelated sports story", source_type="news", connector="test"),
    ]
    survivors, rejected = run_keyword_gate(items, PROFILE)
    assert len(survivors) == 1
    assert len(rejected) == 1
    assert survivors[0]["_gate"]["passed"]


def test_ai_score_skips_gracefully_without_api_key():
    items = [make_item(title="CBDC pilot expands", source_type="news", connector="test")]
    result = ai_score(items, {"title": "CBDC"}, api_key="")
    assert result["scores"] == {}
    assert result["health"]["ok"] is False
    assert "no ANTHROPIC_API_KEY" in result["health"]["note"]
