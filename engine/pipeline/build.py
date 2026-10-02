"""Render the static site from data/ into site/_build/ (gitignored — built
fresh by the Pages workflow each run, same as both reference repos).
"""
from __future__ import annotations

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
        items.append(item)
    items.sort(key=lambda it: it.get("date") or "", reverse=True)
    return items


def build() -> dict:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, OUT_DIR / "static")

    env = _env()
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
        topic_dir = OUT_DIR / slug
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "index.html").write_text(
            topic_tmpl.render(
                root="../",
                all_topics=all_topics,
                active_slug=slug,
                topic=profile,
                items=items,
                groups=sorted(groups.items()),
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
