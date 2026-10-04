"""Venue resolution — shapes taken from real OpenAlex records inspected
live on 2026-10-04 while chasing why so many corpus items read "Zenodo
(CERN European Organization for Nuclear Research)" or had no venue."""

from engine.connectors.openalex import clean_source_name, pick_venue

ZENODO = {
    "display_name": "Zenodo (CERN European Organization for Nuclear Research)",
    "type": "repository",
    "host_organization_name": "European Organization for Nuclear Research",
}
ROUTLEDGE = {"display_name": "Routledge eBooks", "type": "ebook platform", "host_organization_name": "Taylor & Francis"}
JOURNAL = {"display_name": "Applied Economics", "type": "journal", "host_organization_name": "Taylor & Francis"}


def test_clean_source_name_drops_the_host_org_parenthetical():
    assert clean_source_name(ZENODO) == "Zenodo"
    assert clean_source_name(
        {"display_name": "arXiv (Cornell University)", "type": "repository", "host_organization_name": "Cornell University"}
    ) == "arXiv"


def test_clean_source_name_leaves_unrelated_brackets_alone():
    # Only the recorded host org is trimmed, so a real name keeps its brackets.
    source = {"display_name": "Review (Fernand Braudel Center)", "type": "journal", "host_organization_name": "Duke University Press"}
    assert clean_source_name(source) == "Review (Fernand Braudel Center)"


def test_publisher_wins_over_the_repository_holding_a_copy():
    # The real failure: a Routledge book chapter deposited in Zenodo was
    # being attributed to Zenodo/CERN instead of Routledge.
    work = {
        "primary_location": {"source": ZENODO},
        "locations": [{"source": ZENODO}, {"source": ROUTLEDGE}],
    }
    venue, repository = pick_venue(work)
    assert venue == "Routledge eBooks"
    assert repository == "Zenodo"  # kept, but no longer masquerading as the venue


def test_repository_is_kept_when_it_really_is_the_only_source():
    # A standalone Zenodo deposit (e.g. that conference abstract) has no
    # underlying publisher to recover — don't invent one, and don't blank it.
    work = {"primary_location": {"source": ZENODO}, "locations": [{"source": ZENODO}]}
    venue, repository = pick_venue(work)
    assert venue == "Zenodo"
    assert repository == ""  # not duplicated into extra when it *is* the venue


def test_journal_in_primary_location_is_used_as_is():
    work = {"primary_location": {"source": JOURNAL}, "locations": [{"source": JOURNAL}]}
    assert pick_venue(work) == ("Applied Economics", "")


def test_work_with_no_usable_source_yields_empty_venue():
    assert pick_venue({"primary_location": {}, "locations": [{"source": {}}]}) == ("", "")


def test_primary_location_counted_even_if_missing_from_locations():
    work = {"primary_location": {"source": JOURNAL}, "locations": []}
    assert pick_venue(work)[0] == "Applied Economics"
