from engine.pipeline.items import make_item
from engine.pipeline.review import issue_body, parse_review

PROFILE = {"slug": "cbdc", "title": "Central Bank Digital Currencies"}


def test_issue_body_and_parse_review_roundtrip():
    items = [
        make_item(title="A relevant CBDC article", source_type="article", connector="openalex", doi="10.1/a"),
        make_item(title="A relevant CBDC report", source_type="report", connector="worldbank", url="https://wb.org/r"),
    ]
    items[0]["_ai_relevance"] = 3
    items[0]["_ai_reason"] = "central to the topic"
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


def test_parse_review_respects_manual_unticking():
    items = [make_item(title="Borderline item", source_type="news", connector="rss", url="https://x.com/1")]
    items[0]["_ai_relevance"] = 3  # would be pre-ticked and starred
    body = issue_body(items, PROFILE, run_label="2026-10")

    # Kevin unticks it before closing the issue.
    edited = body.replace("[x]", "[ ]")
    parsed = parse_review(edited)
    assert items[0]["id"] not in parsed["accepted"]
    assert items[0]["id"] in parsed["all"]
