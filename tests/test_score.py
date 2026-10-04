from engine.pipeline.items import make_item
from engine.pipeline.score import ai_score, keyword_gate, parse_score_response, run_keyword_gate
from engine.pipeline.score import _quality_context

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


def test_keyword_gate_excludes_a_muted_venue_even_when_keywords_match():
    # Backs the site's "mute source" control: muting a venue has to stop it
    # reaching the review queue, not just hide it in one browser. Venue
    # names mostly come from OpenAlex, so this can't be done in
    # registry/outlets.yaml.
    profile = dict(PROFILE, excluded_venues=["Zenodo"])
    item = make_item(title="A CBDC paper", source_type="article", connector="openalex", venue="Zenodo", doi="10.1/z")
    gate = keyword_gate(item, profile)
    assert not gate["passed"]
    assert "excluded venue" in gate["reason"]


def test_keyword_gate_venue_exclusion_is_case_insensitive_and_exact():
    profile = dict(PROFILE, excluded_venues=["zenodo"])
    muted = make_item(title="A CBDC paper", source_type="article", connector="openalex", venue="Zenodo", doi="10.1/a")
    assert not keyword_gate(muted, profile)["passed"]
    # ...but it must not swallow a different venue that merely contains it
    other = make_item(title="A CBDC paper", source_type="article", connector="openalex", venue="Zenodo Review of Economics", doi="10.1/b")
    assert keyword_gate(other, profile)["passed"]


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


def test_parse_score_response_extracts_quality_tier():
    text = (
        'Here is the JSON:\n'
        '[{"id": "abc1234567", "relevance": 3, "quality": "high", "tags": ["cbdc"], "reason": "central"}]'
    )
    rows = parse_score_response(text)
    assert rows == [{"id": "abc1234567", "relevance": 3, "quality": "high", "tags": ["cbdc"], "reason": "central"}]


def test_parse_score_response_rejects_invalid_quality_value():
    # The model should only ever say high/medium/low, but don't trust it
    # blindly -- an out-of-vocabulary value becomes None (shown as
    # "unscored" on the site) rather than silently accepted as a real tier.
    text = '[{"id": "abc1234567", "relevance": 2, "quality": "very good", "tags": [], "reason": "x"}]'
    rows = parse_score_response(text)
    assert rows[0]["quality"] is None


def test_parse_score_response_handles_no_json_found():
    assert parse_score_response("the model refused to answer") == []


def test_quality_context_names_heterodox_sources_not_mainstream_ones():
    registry = {"heterodox_and_global_south_sources": ["Tricontinental: Institute for Social Research", "CODESRIA"]}
    context = _quality_context(registry)
    assert "Tricontinental" in context
    assert "CODESRIA" in context


def test_quality_context_empty_registry_is_harmless():
    assert _quality_context({}) == ""
