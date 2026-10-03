from engine.pipeline.items import make_item
from engine.pipeline.review import issue_bodies, issue_body, parse_review

PROFILE = {"slug": "cbdc", "title": "Central Bank Digital Currencies"}


def test_issue_body_and_parse_review_roundtrip():
    items = [
        make_item(title="A relevant CBDC article", source_type="article", connector="openalex", doi="10.1/a"),
        make_item(title="A relevant CBDC report", source_type="report", connector="worldbank", url="https://wb.org/r"),
    ]
    items[0]["_ai_relevance"] = 3
    items[0]["_ai_quality"] = "high"
    items[0]["_ai_reason"] = "central to the topic"
    items[0]["_ai_tags"] = ["cbdc", "wholesale"]
    items[1]["_gate"] = {"passed": True, "matched_terms": ["cbdc", "digital"], "reason": "matched"}

    body = issue_body(items, PROFILE, run_label="2026-10")
    assert items[0]["id"] in body
    assert items[1]["id"] in body
    assert "★" in body  # relevance-3 item should be starred

    parsed = parse_review(body)
    # Both items are pre-ticked: item 0 by ai_relevance>=2, item 1 by gate heuristic.
    assert items[0]["id"] in parsed["accepted"]
    assert items[1]["id"] in parsed["accepted"]
    assert items[0]["id"] in parsed["featured"]
    assert parsed["all"] == {items[0]["id"], items[1]["id"]}

    # Quality/relevance/tags round-trip through the HTML comment for the
    # scored item; the gate-only item (never AI-scored) comes back empty,
    # not a wrong guess.
    assert parsed["meta"][items[0]["id"]] == {"quality": "high", "relevance": 3, "tags": ["cbdc", "wholesale"]}
    assert parsed["meta"][items[1]["id"]] == {"quality": None, "relevance": None, "tags": []}


def test_review_roundtrip_handles_hyphenated_tags():
    # Regression guard: tags like "e-cny" or "cross-border" contain hyphens,
    # so the comment's tags segment must be matched non-greedily up to the
    # literal "-->", not with a naive [^-]* that would truncate early.
    item = make_item(title="e-CNY cross-border pilot", source_type="news", connector="rss", url="https://x.com/1")
    item["_ai_relevance"] = 2
    item["_ai_quality"] = "medium"
    item["_ai_tags"] = ["e-cny", "cross-border"]
    body = issue_body([item], PROFILE, run_label="2026-10")
    parsed = parse_review(body)
    assert parsed["meta"][item["id"]]["tags"] == ["e-cny", "cross-border"]


def test_parse_review_respects_manual_unticking():
    items = [make_item(title="Borderline item", source_type="news", connector="rss", url="https://x.com/1")]
    items[0]["_ai_relevance"] = 3  # would be pre-ticked and starred
    body = issue_body(items, PROFILE, run_label="2026-10")

    # Kevin unticks it before closing the issue.
    edited = body.replace("[x]", "[ ]")
    parsed = parse_review(edited)
    assert items[0]["id"] not in parsed["accepted"]
    assert items[0]["id"] in parsed["all"]


def test_issue_bodies_returns_one_part_when_it_fits():
    items = [make_item(title="A relevant CBDC article", source_type="article", connector="openalex", doi="10.1/a")]
    parts = issue_bodies(items, PROFILE, run_label="2026-10")
    assert len(parts) == 1
    suffix, body = parts[0]
    assert suffix == ""
    assert items[0]["id"] in body


def test_issue_bodies_splits_when_over_the_limit_regression():
    # Regression test for a real failure on the first live harvest run
    # (2026-10-03): GitHub's createIssue rejected the body with "Body is
    # too long (maximum is 65536 characters)" once GDELT/RSS results were
    # added on top of OpenAlex's — this repo's own local smoke test alone
    # produced a 60KB body from OpenAlex results for one topic.
    items = [
        make_item(
            title=f"CBDC working paper number {i} with a reasonably long descriptive title",
            source_type="article", connector="openalex", doi=f"10.1/item-{i}",
            abstract="x" * 50,
        )
        for i in range(400)
    ]
    parts = issue_bodies(items, PROFILE, run_label="2026-10", max_chars=5000)
    assert len(parts) > 1

    all_ids_seen = set()
    for i, (suffix, body) in enumerate(parts, start=1):
        assert f"part {i} of {len(parts)}" in suffix
        assert len(body) <= 5000 + 500  # a little slack for the heading/intro overhead on each part
        parsed = parse_review(body)
        all_ids_seen |= parsed["all"]

    # Every item appears in exactly one part, none lost, none duplicated.
    assert all_ids_seen == {it["id"] for it in items}
    total_occurrences = sum(len(parse_review(body)["all"]) for _suffix, body in parts)
    assert total_occurrences == len(items)
