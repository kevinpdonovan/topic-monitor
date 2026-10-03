from unittest.mock import MagicMock, patch

from engine.wizard.expand import expand_seed_terms

FAKE_PAGE = {
    "meta": {"next_cursor": None},
    "results": [
        {
            "title": "Damp housing and respiratory health in the UK",
            "concepts": [
                {"display_name": "Biology", "level": 0, "score": 0.6},  # too broad -- dropped
                {"display_name": "Medicine", "level": 0, "score": 0.9},  # too broad -- dropped
                {"display_name": "Cladosporium", "level": 3, "score": 0.5},  # specific, kept
                {"display_name": "weak signal", "level": 3, "score": 0.1},  # below score threshold -- dropped
            ],
            "keywords": [
                {"display_name": "indoor air quality", "score": 0.8},
                {"display_name": "mould", "score": 0.9},  # matches a seed term -- dropped
            ],
        }
    ],
}


def _fake_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


@patch("engine.wizard.expand.make_session")
def test_expand_seed_terms_filters_broad_concepts_and_seed_terms(mock_make_session):
    session = MagicMock()
    session.get.return_value = _fake_response(FAKE_PAGE)
    mock_make_session.return_value = session

    result = expand_seed_terms(["mould"], contact_email="x@example.com", sample_size=10)

    terms = {c["term"] for c in result["candidates"]}
    assert "Cladosporium" in terms
    assert "indoor air quality" in terms
    assert "Biology" not in terms  # level 0, too broad
    assert "Medicine" not in terms  # level 0, too broad
    assert "weak signal" not in terms  # below score threshold
    assert "mould" not in terms  # matches the seed term itself
    assert result["sampled_titles"] == 1


@patch("engine.wizard.expand.make_session")
def test_expand_seed_terms_ranks_by_total_score_not_raw_count(mock_make_session):
    # Two pages: term A appears once with a high score, term B appears
    # twice with a low score each time. Regression guard for the real
    # finding (2026-10-03, seeding "mould"+"housing UK"): ranking by raw
    # frequency surfaced generic broad-field tags ahead of specific, more
    # useful ones that scored higher but occurred less often.
    page_a = {
        "meta": {"next_cursor": "page2"},
        "results": [{"title": "t1", "concepts": [{"display_name": "term A", "level": 2, "score": 0.9}], "keywords": []}],
    }
    page_b = {
        "meta": {"next_cursor": None},
        "results": [
            {"title": "t2", "concepts": [{"display_name": "term B", "level": 2, "score": 0.31}], "keywords": []},
            {"title": "t3", "concepts": [{"display_name": "term B", "level": 2, "score": 0.31}], "keywords": []},
        ],
    }
    session = MagicMock()
    session.get.side_effect = [_fake_response(page_a), _fake_response(page_b)]
    mock_make_session.return_value = session

    result = expand_seed_terms(["x"], contact_email="x@example.com", sample_size=10)
    ranked_terms = [c["term"] for c in result["candidates"]]
    assert ranked_terms[0] == "term A"  # 0.9 total > 0.62 total, despite fewer occurrences
