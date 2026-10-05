"""Render the static site from data/ into site/_build/ (gitignored — built
fresh by the Pages workflow each run, same as both reference repos).

Each topic page is server-rendered (works with no JS: all accepted items,
grouped by type) *and* ships an items.json the page's own JS reads to add
search, a quality-tier filter, and an all-time/by-month view toggle — see
site/static/topic.js. Added 2026-10-03 at Kevin's request.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from engine.pipeline.corpus import Corpus, DecisionStore
from engine.pipeline.health import load_health
from engine.pipeline.profile import REPO_ROOT, list_topics, load_profile

SITE_DIR = REPO_ROOT / "site"
TEMPLATES_DIR = SITE_DIR / "templates"
STATIC_DIR = SITE_DIR / "static"
OUT_DIR = SITE_DIR / "_build"
DATA_DIR = REPO_ROOT / "data"


def _site_config() -> dict:
    """Optional site/config.yaml. Absent or empty is fine — every consumer
    treats a missing value as "feature off" rather than an error."""
    import yaml

    path = SITE_DIR / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _env(root: str = "") -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _topic_items(slug: str, corpus: Corpus) -> list:
    decisions = DecisionStore(DATA_DIR / "decisions" / f"{slug}.jsonl")
    items = []
    for decision in decisions.accepted():
        item = corpus.get(decision["id"])
        if not item:
            continue
        item = dict(item)
        item["featured"] = decision.get("featured", False)
        item["quality"] = decision.get("quality")
        item["relevance"] = decision.get("relevance")
        item["tags"] = decision.get("tags", [])
        items.append(item)
    items.sort(key=lambda it: it.get("date") or "", reverse=True)
    return items


def _month_key(item: dict) -> str:
    date = item.get("date") or ""
    return date[:7] if len(date) >= 7 else "undated"


def _items_json(items: list) -> str:
    """Flat JSON index for the topic page's client-side search/filter/
    monthly-view JS (site/static/topic.js) — see module docstring."""
    rows = [
        {
            "id": it["id"],
            "title": it["title"],
            "url": it.get("url") or it.get("pdf_url") or "",
            "authors": it.get("authors") or [],
            "organisation": it.get("organisation", ""),
            "venue": it.get("venue", ""),
            "date": it.get("date", ""),
            "month": _month_key(it),
            "source_type": it.get("source_type", "article"),
            "quality": it.get("quality"),
            "relevance": it.get("relevance"),
            "tags": it.get("tags") or [],
            "featured": bool(it.get("featured")),
            "abstract": (it.get("abstract") or "")[:400],
        }
        for it in items
    ]
    return json.dumps(rows, ensure_ascii=False)


def build() -> dict:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, OUT_DIR / "static")

    env = _env()
    site_config = _site_config()
    corpus = Corpus(DATA_DIR / "items.jsonl")
    slugs = list_topics(status=None)  # include paused topics so old pages don't 404
    all_topics = []
    topic_summaries = []

    for slug in slugs:
        profile = load_profile(slug)
        items = _topic_items(slug, corpus)
        all_topics.append({"slug": slug, "title": profile.get("title", slug)})
        topic_summaries.append(
            {"slug": slug, "title": profile.get("title", slug), "accepted_count": len(items), "cadence": profile.get("cadence", "")}
        )

    index_tmpl = env.get_template("index.html")
    (OUT_DIR / "index.html").write_text(
        index_tmpl.render(root="", all_topics=all_topics, active_slug=None, topics=topic_summaries),
        encoding="utf-8",
    )

    topic_tmpl = env.get_template("topic.html")
    for slug in slugs:
        profile = load_profile(slug)
        items = _topic_items(slug, corpus)
        groups: dict = {}
        for item in items:
            groups.setdefault(item.get("source_type", "article"), []).append(item)
        # Same split the JS layer uses (see site/static/topic.js): articles
        # left, everything else right, so the two agree and the page doesn't
        # visibly reflow when the JS takes over.
        groups_left = sorted((t, g) for t, g in groups.items() if t == "article")
        groups_right = sorted((t, g) for t, g in groups.items() if t != "article")
        topic_dir = OUT_DIR / slug
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "items.json").write_text(_items_json(items), encoding="utf-8")
        (topic_dir / "index.html").write_text(
            topic_tmpl.render(
                marks_api=site_config.get("marks_api", ""),
                root="../",
                all_topics=all_topics,
                active_slug=slug,
                topic=profile,
                items=items,
                groups_left=groups_left,
                groups_right=groups_right,
            ),
            encoding="utf-8",
        )

    health = load_health(DATA_DIR / "health" / "latest.json")
    health_tmpl = env.get_template("health.html")
    (OUT_DIR / "health.html").write_text(
        health_tmpl.render(root="", all_topics=all_topics, active_slug="health", health=health),
        encoding="utf-8",
    )

    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    return {"topics": len(slugs), "pages": len(slugs) + 2}
