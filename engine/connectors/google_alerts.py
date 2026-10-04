"""Google Alerts feed cleanup.

Google Alerts has no API. Kevin creates each alert by hand in his own
account and pastes the feed URL into the topic profile — the build brief
is explicit that nothing here may script a logged-in browser to create
one. The feed itself is ordinary Atom, so `connectors.rss.harvest_rss`
does the fetching and parsing; this module only handles the two
Google-specific quirks that would otherwise corrupt the pipeline:

1. **Redirect links.** Entry links are
   `https://www.google.com/url?rct=j&sa=t&url=<real url>&ct=ga&...`
   wrappers, not the article itself. Left alone they'd break dedup (the
   same article arriving via GDELT or an outlet feed has the real URL, so
   the two would never collapse — `item_id` is derived from the URL), and
   every link on the site would point at a google.com redirect. Unwrapped
   back to the target URL.

2. **Markup in text.** Titles and summaries come back with `<b>` tags
   around the matched query terms, plus HTML entities. Stripped, so the
   review issue and the site show clean text rather than escaped markup.
"""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlsplit

_TAG_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")

GOOGLE_REDIRECT_HOSTS = {"google.com", "www.google.com", "news.google.com"}


def unwrap_redirect(url: str) -> str:
    """Return the real target of a Google redirect URL, or `url` unchanged
    if it isn't one (or doesn't carry a usable target)."""
    if not url:
        return url
    parts = urlsplit(url)
    if parts.netloc.lower() not in GOOGLE_REDIRECT_HOSTS:
        return url
    target = parse_qs(parts.query).get("url", [""])[0]
    if not target.startswith(("http://", "https://")):
        return url
    return target


def strip_markup(text: str) -> str:
    """Drop HTML tags and unescape entities, collapsing whitespace."""
    if not text:
        return text
    return _WS_RX.sub(" ", html.unescape(_TAG_RX.sub("", text))).strip()


def transform(title: str, url: str, summary: str) -> tuple:
    """The `transform` hook `harvest_rss` applies per source."""
    return strip_markup(title), unwrap_redirect(url), strip_markup(summary)
