from datetime import date

from engine.pipeline.backfill import (
    backfill_date_from,
    min_citations_for_age,
    passes_citation_prefilter,
    run_citation_prefilter,
)
from engine.pipeline.items import make_item

TODAY = date(2026, 10, 3)


def test_min_citations_for_age_zero_within_grace_period():
    assert min_citations_for_age(0) == 0
    assert min_citations_for_age(90) == 0  # exactly at the boundary, still free


def test_min_citations_for_age_grows_linearly_beyond_grace_period():
    # default: 90-day grace period, 1 citation/month beyond it
    assert min_citations_for_age(91) == 1      # just past the boundary -> rounds up to 1 month's worth
    assert min_citations_for_age(90 + 30) == 1
    assert min_citations_for_age(90 + 60) == 2
    assert min_citations_for_age(90 + 365) >= 12  # a year beyond the grace period needs double digits


def test_min_citations_for_age_respects_custom_rate():
    # a gentler rate (0.5 citations/month) should roughly halve the bar
    strict = min_citations_for_age(90 + 180, citations_per_month=1.0)
    gentle = min_citations_for_age(90 + 180, citations_per_month=0.5)
    assert gentle < strict


def _oa_item(title: str, *, date_str: str, citations):
    return make_item(
        title=title, source_type="article", connector="openalex", doi=f"10.1/{title}",
        date=date_str, extra={"cited_by_count": citations},
    )


def test_recent_item_with_zero_citations_passes():
    item = _oa_item("brand new paper", date_str="2026-09-20", citations=0)
    assert passes_citation_prefilter(item, today=TODAY)


def test_old_item_with_zero_citations_is_dropped():
    item = _oa_item("old uncited paper", date_str="2021-01-01", citations=0)
    assert not passes_citation_prefilter(item, today=TODAY)


def test_old_item_with_enough_citations_survives():
    # ~5.7 years old -> needs a real citation count, but a well-cited paper clears it
    item = _oa_item("old influential paper", date_str="2021-01-01", citations=100)
    assert passes_citation_prefilter(item, today=TODAY)


def test_missing_citation_count_never_silently_excludes():
    # Kevin's instruction was explicit about not penalizing on absence of
    # a signal -- an item we simply don't have a citation count for (e.g.
    # a non-OpenAlex source, if this ever runs over one) should pass, not
    # get dropped as if it had zero.
    item = make_item(title="no citation data", source_type="article", connector="other", date="2020-01-01")
    assert passes_citation_prefilter(item, today=TODAY)


def test_missing_date_never_silently_excludes():
    item = _oa_item("no date on record", date_str="", citations=0)
    assert passes_citation_prefilter(item, today=TODAY)


def test_run_citation_prefilter_splits_survivors_and_dropped():
    items = [
        _oa_item("new", date_str="2026-09-01", citations=0),
        _oa_item("old uncited", date_str="2020-01-01", citations=0),
        _oa_item("old well-cited", date_str="2020-01-01", citations=200),
    ]
    survivors, dropped = run_citation_prefilter(items, today=TODAY)
    assert {it["title"] for it in survivors} == {"new", "old well-cited"}
    assert {it["title"] for it in dropped} == {"old uncited"}


def test_backfill_date_from_one_year():
    result = backfill_date_from(1, today=TODAY)
    assert result == "2025-10-03"


def test_backfill_date_from_is_extensible_to_more_years():
    result = backfill_date_from(5, today=TODAY)
    assert result.startswith("2021-")
