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
    summary = (entry.get("summary") or entry.get("description") or "").strip()

    # Optional per-source cleanup, applied *before* make_item so the
    # item id is computed from the real URL. Google Alerts needs this:
    # its entry links are google.com/url?...&url=<real> redirects, which
    # would otherwise never dedupe against the same article arriving via
    # GDELT or an outlet feed. See connectors/google_alerts.py.
    transform = source.get("transform")
    if transform:
        title, url, summary = transform(title, url, summary)

    if not title or not url:
        return None
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
                    # An outlet feed returning nothing means something
                    # broke. A Google Alert returning nothing just means
                    # Google hasn't matched anything since the alert was
                    # created — confirmed live 2026-10-04 against Kevin's
                    # brand-new CBDC alert, which served a valid, entirely
                    # empty Atom feed. Flagging that as a failure would
                    # give the health page a permanent false alarm (and a
                    # climbing fail_streak) for a source working exactly
                    # as intended, so sources can opt out via empty_ok.
                    if source.get("empty_ok"):
                        note = "no matches yet (0 entries, expected for a quiet alert)"
                    else:
                        ok = False
                        note = "0 entries returned"
        except Exception as exc:  # feedparser swallows most errors into bozo, but be defensive
            ok = False
            note = str(exc)
        health.append({"source": f"{source.get('connector', 'rss')}:{source_id}", "ok": ok, "count": count, "note": note})
    return items, health
