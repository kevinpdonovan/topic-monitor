"""The one item schema every connector returns. Nothing topic-specific here."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE_TYPES = {
    "article", "book", "chapter", "working_paper", "report",
    "policy_document", "news", "discourse", "podcast",
}

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "mc_cid", "mc_eid",
}


def clean_url(url: str) -> str:
    """Normalise a URL for dedup/id purposes: strip tracking params, trailing slash, scheme/host case."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def item_id(doi: str = "", url: str = "", title: str = "") -> str:
    """Deterministic id: DOI wins, else cleaned URL, else slugified title.

    Two connectors that both supply the same DOI (or the same URL, or
    lacking either, the same title) collapse to the same id automatically —
    this is the first, cheapest layer of dedup, before pipeline.dedupe runs.
    """
    key = (doi or "").strip().lower() or clean_url(url) or _slug(title)
    if not key:
        raise ValueError("item_id needs at least one of doi, url, title")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


@dataclass
class Item:
    id: str
    title: str
    source_type: str
    connector: str
    url: str = ""
    pdf_url: str = ""
    doi: str = ""
    isbn: str = ""
    authors: list = field(default_factory=list)
    organisation: str = ""
    date: str = ""
    language: str = "en"
    abstract: str = ""
    venue: str = ""
    origin: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def make_item(
    *,
    title: str,
    source_type: str,
    connector: str,
    url: str = "",
    pdf_url: str = "",
    doi: str = "",
    isbn: str = "",
    authors=None,
    organisation: str = "",
    date: str = "",
    language: str = "en",
    abstract: str = "",
    venue: str = "",
    origin=None,
    extra=None,
) -> dict:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source_type {source_type!r}, must be one of {sorted(SOURCE_TYPES)}")
    if not title or not title.strip():
        raise ValueError("item needs a title")
    doi_n = (doi or "").strip().lower()
    url_n = clean_url(url)
    iid = item_id(doi=doi_n, url=url_n, title=title)
    return Item(
        id=iid,
        title=title.strip(),
        source_type=source_type,
        connector=connector,
        url=url_n,
        pdf_url=pdf_url or "",
        doi=doi_n,
        isbn=(isbn or "").strip(),
        authors=list(authors or []),
        organisation=organisation or "",
        date=date or "",
        language=language or "en",
        abstract=(abstract or "").strip(),
        venue=venue or "",
        origin=list(origin or []),
        extra=extra or {},
    ).to_dict()
