import json
from pathlib import Path

import pytest

from engine.connectors.openalex import _to_item

FIXTURES = Path(__file__).parent / "fixtures"


def test_openalex_to_item_parses_recorded_response():
    # Recorded live from api.openalex.org on 2026-10-02 (search="central bank
    # digital currency", per-page=3) — see CLAUDE.md / ground rule 4.
    payload = json.loads((FIXTURES / "openalex_sample.json").read_text())
    works = payload["results"]
    assert len(works) == 3

    items = [item for item in (_to_item(w) for w in works) if item]
    assert len(items) == 3
    for item in items:
        assert item["title"]
        assert item["source_type"] in ("article", "book", "chapter", "report")
        assert item["connector"] == "openalex"

    # abstract_inverted_index reconstruction: at least one item should have
    # a non-empty abstract if the source record had one.
    any_abstract = any(item["abstract"] for item in items)
    any_had_index = any(w.get("abstract_inverted_index") for w in works)
    assert any_abstract == any_had_index


def test_rss_connector_parses_a_real_recorded_feed():
    pytest.importorskip("feedparser", reason="feedparser needs Python >=3.9; this sandbox has 3.7 — verify for real via the GitHub Actions run (Python 3.12) instead")
    from engine.connectors.rss import harvest_rss

    source = {
        "id": "bis-speeches",
        "url": str(FIXTURES / "bis_speeches_rdf.xml"),  # recorded 2026-10-02; feedparser reads local paths fine
        "venue": "BIS central bank speeches",
        "source_type": "policy_document",
        "connector": "outlet_rss",
    }
    items, health = harvest_rss([source])
    assert health[0]["ok"] is True
    assert health[0]["count"] > 0
    assert len(items) == health[0]["count"]
    assert all(item["source_type"] == "policy_document" for item in items)
