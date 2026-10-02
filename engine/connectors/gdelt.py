"""GDELT DOC API connector: global news by query.

GDELT rate-limits aggressively and shares limits across source IP, which
both reference repos hit in production (insubordinate-terminal's health.json
shows 429s; this repo's own live test from the build sandbox also got 429
on 2026-10-02, recovering was not possible within a short retry window from
that IP). Ground rule: one request at a time, with backoff, and a connector
that reports `ok: false` honestly rather than retrying forever.
"""
from __future__ import annotations

import time

import requests

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _to_item(article: dict):
    from engine.pipeline.items import make_item

    title = (article.get("title") or "").strip()
    url = article.get("url") or ""
    if not title or not url:
        return None
    return make_item(
        title=title,
        source_type="news",
        connector="gdelt",
        url=url,
        date=article.get("seendate") or "",
        venue=article.get("domain") or "",
        language=article.get("language") or "en",
        extra={"sourcecountry": article.get("sourcecountry")},
    )


def harvest_gdelt(
    queries: list,
    *,
    max_records: int = 50,
    timespan: str = "1month",
    pause_seconds: float = 6.0,
    timeout: int = 20,
) -> tuple:
    """Run each query against the GDELT DOC API. Returns (items, health).

    One request at a time with a `pause_seconds` gap, per the rate-limit
    lesson above. A 429 is reported as a health failure, not retried —
    GDELT's limit window is long enough that hammering it just extends the
    outage for the next connector that needs it this run.
    """
    items = []
    health = []
    for i, query in enumerate(queries):
        if i > 0:
            time.sleep(pause_seconds)
        count = 0
        ok = True
        note = ""
        try:
            params = {
                "query": query,
                "mode": "artlist",
                "maxrecords": max_records,
                "timespan": timespan,
                "format": "json",
            }
            resp = requests.get(API_URL, params=params, timeout=timeout)
            if resp.status_code == 429:
                ok = False
                note = "HTTP 429 rate-limited"
            elif resp.status_code != 200:
                ok = False
                note = f"HTTP {resp.status_code}"
            else:
                payload = resp.json()
                for article in payload.get("articles", []) or []:
                    item = _to_item(article)
                    if item:
                        items.append(item)
                        count += 1
        except requests.RequestException as exc:
            ok = False
            note = str(exc)
        except ValueError as exc:
            ok = False
            note = f"bad JSON response: {exc}"
        health.append({"source": f"gdelt:{query}", "ok": ok, "count": count, "note": note})
    return items, health
