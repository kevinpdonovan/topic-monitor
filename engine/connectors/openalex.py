"""OpenAlex connector: keyword queries over the scholarship/books/reports graph.

Free, no key required — uses the "polite pool" via a contact email in the
User-Agent, which in practice means far fewer timeouts. Confirmed live
2026-10-02: a plain keyword search against api.openalex.org returned 200
with real results (82,729 hits for "central bank digital currency").
"""
from __future__ import annotations

import time

import requests

API_URL = "https://api.openalex.org/works"

# OpenAlex `type` -> our source_type. Falls back to "article" for anything
# not listed (dataset/grant/paratext/erratum are rare and not worth a
# dedicated channel).
TYPE_MAP = {
    "article": "article",
    "preprint": "article",
    "dissertation": "article",
    "editorial": "article",
    "letter": "article",
    "review": "article",
    "book": "book",
    "book-chapter": "chapter",
    "report": "report",
    "standard": "report",
}


def make_session(contact_email: str) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = f"topic-monitor/0.1 (mailto:{contact_email})"
    return s


def _to_item(work: dict):
    from engine.pipeline.items import make_item

    title = (work.get("title") or work.get("display_name") or "").strip()
    if not title:
        return None
    oa_type = work.get("type") or "article"
    source_type = TYPE_MAP.get(oa_type, "article")

    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    primary = work.get("primary_location") or {}
    url = primary.get("landing_page_url") or work.get("id") or ""
    pdf_url = primary.get("pdf_url") or ""
    venue = ((primary.get("source") or {}) or {}).get("display_name") or ""

    authors = []
    for a in work.get("authorships", []) or []:
        name = (a.get("author") or {}).get("display_name")
        if name:
            authors.append(name)

    abstract = ""
    inv = work.get("abstract_inverted_index")
    if inv:
        positions = {}
        for word, idxs in inv.items():
            for i in idxs:
                positions[i] = word
        abstract = " ".join(positions[i] for i in sorted(positions))

    return make_item(
        title=title,
        source_type=source_type,
        connector="openalex",
        url=url,
        pdf_url=pdf_url,
        doi=doi,
        authors=authors,
        date=work.get("publication_date") or "",
        abstract=abstract[:2000],
        venue=venue,
        extra={"openalex_id": work.get("id"), "cited_by_count": work.get("cited_by_count")},
    )


def harvest_openalex(
    queries: list,
    *,
    contact_email: str,
    per_page: int = 50,
    max_pages: int = 3,
    date_from: str | None = None,
    timeout: int = 20,
) -> tuple:
    """Run each query as an OpenAlex keyword search. Returns (items, health)."""
    if not contact_email:
        raise ValueError("harvest_openalex needs a contact_email for the polite pool")
    session = make_session(contact_email)
    items = []
    health = []
    for query in queries:
        count = 0
        ok = True
        note = ""
        try:
            cursor = "*"
            for _ in range(max_pages):
                params = {
                    "search": query,
                    "per-page": per_page,
                    "cursor": cursor,
                }
                filters = []
                if date_from:
                    filters.append(f"from_publication_date:{date_from}")
                if filters:
                    params["filter"] = ",".join(filters)
                resp = session.get(API_URL, params=params, timeout=timeout)
                if resp.status_code != 200:
                    ok = False
                    note = f"HTTP {resp.status_code}"
                    break
                payload = resp.json()
                for work in payload.get("results", []):
                    item = _to_item(work)
                    if item:
                        items.append(item)
                        count += 1
                cursor = (payload.get("meta") or {}).get("next_cursor")
                if not cursor:
                    break
                time.sleep(0.15)
        except requests.RequestException as exc:
            ok = False
            note = str(exc)
        health.append({"source": f"openalex:{query}", "ok": ok, "count": count, "note": note})
    return items, health
