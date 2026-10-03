"""One-time historical backfill: pull scholarship further back than the
normal monthly cycle's 12-month window, then cull the resulting volume
with an age-weighted citation pre-filter before the (costly) AI scoring
stage runs over it.

Scholarship only (OpenAlex) — GDELT and the RSS outlets only expose
recent items through their feeds, there is no multi-year history
available through those connectors. A backfill is a deliberate, manually
triggered, long-running job (see .github/workflows/backfill.yml), not
part of the regular monthly cadence — re-running the same multi-year
window every cycle would be slow and pointless once the corpus already
has it.

Why age-weighted citations, not a flat cutoff (Kevin, 2026-10-03): a flat
citation minimum would penalize recent work for not having had time to
accumulate citations yet — exactly the bias the quality-tier rubric in
score.py was built to avoid. A paper from last month legitimately has
~0 citations regardless of how good it is. So this pre-filter uses a
grace period (recent items always pass it, regardless of citations) and
only requires progressively more citations as an item ages — it's a
*volume-reduction* step for an otherwise-unmanageable historical batch,
not a quality judgment. The actual quality judgment is still the same
AI rubric every regular cycle uses, applied afterwards to whatever
survives this cull.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

DEFAULT_GRACE_PERIOD_DAYS = 90
DEFAULT_CITATIONS_PER_MONTH = 1.0


def min_citations_for_age(
    age_days: int,
    *,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    citations_per_month: float = DEFAULT_CITATIONS_PER_MONTH,
) -> int:
    """The citation count an item needs to survive the pre-filter, given
    its age in days. 0 for anything within the grace period; grows
    linearly (by `citations_per_month`, per 30-day month) beyond it.
    """
    if age_days <= grace_period_days:
        return 0
    months_beyond = (age_days - grace_period_days) / 30
    return math.ceil(months_beyond * citations_per_month)


def passes_citation_prefilter(
    item: dict,
    *,
    today: date,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    citations_per_month: float = DEFAULT_CITATIONS_PER_MONTH,
) -> bool:
    """True if `item` clears the age-weighted citation bar, or doesn't have
    enough information to be judged (no date, or no citation count — e.g.
    non-OpenAlex items, which backfill doesn't harvest today but this
    stays safe if that changes) — absence of data should never silently
    exclude an item here.
    """
    raw_date = item.get("date") or ""
    if len(raw_date) < 10:
        return True
    try:
        pub_date = date.fromisoformat(raw_date[:10])
    except ValueError:
        return True
    age_days = (today - pub_date).days
    if age_days < 0:
        age_days = 0

    cited_by = item.get("extra", {}).get("cited_by_count")
    if cited_by is None:
        return True

    return cited_by >= min_citations_for_age(
        age_days, grace_period_days=grace_period_days, citations_per_month=citations_per_month
    )


def run_citation_prefilter(
    items: list,
    *,
    today: date,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    citations_per_month: float = DEFAULT_CITATIONS_PER_MONTH,
) -> tuple:
    """Returns (survivors, dropped)."""
    survivors, dropped = [], []
    for item in items:
        ok = passes_citation_prefilter(
            item, today=today, grace_period_days=grace_period_days, citations_per_month=citations_per_month
        )
        (survivors if ok else dropped).append(item)
    return survivors, dropped


def backfill_date_from(years_back: int, *, today: date | None = None) -> str:
    today = today or date.today()
    return (today - timedelta(days=365 * years_back)).isoformat()
