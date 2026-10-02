"""Generic RSS/Atom connector. Shared by outlet feeds and Google Alerts feeds —
both are just an RSS URL with a per-source default source_type, venue and
organisation. Handles RSS 2.0, RSS 1.0/RDF and Atom uniformly via feedparser
(it does not care about the feed dialect, unlike a hand-rolled XML parser —
see CLAUDE.md for why e.g. BIS's speeches feed is RSS 1.0/RDF and needs
namespace-aware parsing that a plain `.//item` search misses).
"""
from __future__ import annotations

from dateutil import parser as dateparser


def _parse_date(entry) -> str:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                return dateparser.parse(raw, fuzzy=True).date().isoformat()
            except (ValueError, OverflowError):
                continue
    return ""


def _to_item(entry, source: dict):
    from engine.pipeline.items import make_item

    title = (entry.get("title") or "").strip()
    url = entry.get("link") or ""
    if not title or not url:
        return None
    summary = (entry.get("summary") or entry.get("description") or "").strip()
    return make_item(
        title=title,
        source_type=source.get("source_type", "news"),
        connector=source.get("connector", "rss"),
        url=url,
        date=_parse_date(entry),
        abstract=summary[:1000],
        venue=source.get("venue", ""),
        organisation=source.get("organisation", ""),
        language=source.get("language", "en"),
        extra={"feed_id": source.get("id")},
    )


def harvest_rss(sources: list, *, timeout: int = 20) -> tuple:
    """`sources` is a list of dicts: {id, url, venue, organisation?, source_type?,
    connector?, language?}. Returns (items, health), one health row per source.
    """
    import feedparser

    items = []
    health = []
    for source in sources:
        url = source["url"]
        source_id = source.get("id", url)
        count = 0
        ok = True
        note = ""
        try:
            parsed = feedparser.parse(url, agent="topic-monitor/0.1", request_headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
            if parsed.bozo and not parsed.entries:
                ok = False
                note = f"feed parse error: {parsed.bozo_exception}"
            elif getattr(parsed, "status", 200) not in (200, 301, 302, 304, None):
                ok = False
                note = f"HTTP {parsed.status}"
            else:
                for entry in parsed.entries:
                    item = _to_item(entry, source)
                    if item:
                        items.append(item)
                        count += 1
                if count == 0:
                    ok = False
                    note = "0 entries returned"
        except Exception as exc:  # feedparser swallows most errors into bozo, but be defensive
            ok = False
            note = str(exc)
        health.append({"source": f"{source.get('connector', 'rss')}:{source_id}", "ok": ok, "count": count, "note": note})
    return items, health
