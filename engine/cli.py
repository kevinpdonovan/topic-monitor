"""CLI entry points: harvest, publish, build.

`python -m engine harvest` — run connectors once for the union of every
active topic's queries, score against each topic, write a review-issue
markdown file per topic for the Action to open as a GitHub issue.

`python -m engine publish --topic X --issue-body-file F --run R` — parse a
closed review issue back into decisions, update the corpus, rebuild the site.

`python -m engine build` — just re-render the site from current data/.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from engine.connectors.gdelt import harvest_gdelt
from engine.connectors.openalex import harvest_openalex
from engine.connectors.rss import harvest_rss
from engine.pipeline import build as build_mod
from engine.pipeline.corpus import Corpus, DecisionStore
from engine.pipeline.dedupe import dedupe
from engine.pipeline.health import aggregate_health, load_health, save_health
from engine.pipeline.profile import REPO_ROOT, list_topics, load_profile, outlets_for_topic
from engine.pipeline.review import issue_bodies, parse_review
from engine.pipeline.score import ai_score, run_keyword_gate

DATA_DIR = REPO_ROOT / "data"


def _run_label(cadence_hint: str = "") -> str:
    return date.today().isoformat()


def cmd_harvest(args) -> int:
    slugs = [args.topic] if args.topic else list_topics(status="active")
    if not slugs:
        print("no active topics found", file=sys.stderr)
        return 1
    profiles = {slug: load_profile(slug) for slug in slugs}
    contact_email = os.environ.get("CONTACT_EMAIL", "")
    if not contact_email:
        print("CONTACT_EMAIL not set — required for the OpenAlex polite pool", file=sys.stderr)
        return 1
    run_label = _run_label()

    # Union queries across topics so each connector runs once per cycle,
    # not once per topic (the "harvest once, filter many" principle).
    oa_queries: dict = {}
    gdelt_queries: dict = {}
    rss_sources: dict = {}
    for slug, profile in profiles.items():
        connectors = profile.get("connectors", {}) or {}
        for q in (connectors.get("openalex", {}) or {}).get("queries", []):
            oa_queries.setdefault(q, []).append(slug)
        for q in (connectors.get("gdelt", {}) or {}).get("queries", []):
            gdelt_queries.setdefault(q, []).append(slug)
        for src in outlets_for_topic(profile):
            rss_sources.setdefault(src["id"], src)

    all_items = []
    all_health = []

    if oa_queries:
        # Simplification for Phase 1 (one topic): date_from is taken from
        # whichever profile happens to be first, not tracked per-query. Fine
        # with a single topic; once a second topic has a different backfill
        # window this needs to move to a per-query date_from, not a global one.
        date_from = profiles[next(iter(profiles))].get("connectors", {}).get("openalex", {}).get("date_from")
        items, health = harvest_openalex(list(oa_queries), contact_email=contact_email, date_from=date_from)
        all_items += items
        all_health += health

    if gdelt_queries and not args.skip_gdelt:
        items, health = harvest_gdelt(list(gdelt_queries))
        all_items += items
        all_health += health

    if rss_sources:
        items, health = harvest_rss(list(rss_sources.values()))
        all_items += items
        all_health += health

    corpus = Corpus(DATA_DIR / "items.jsonl")
    result = dedupe(all_items, corpus=None)  # keep already-seen items in the pool; topics decide per-topic what's new
    deduped = result["items"]
    print(f"harvested {len(all_items)} raw -> {len(deduped)} after dedupe (rate {result['stats']['duplicate_rate']:.1%})")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    tagger_model = os.environ.get("TAGGER_MODEL", "claude-haiku-4-5")

    for slug, profile in profiles.items():
        decisions = DecisionStore(DATA_DIR / "decisions" / f"{slug}.jsonl")
        already_decided = decisions.decided_ids()

        survivors, _rejected = run_keyword_gate(deduped, profile)
        candidates = [it for it in survivors if it["id"] not in already_decided]
        for it in candidates:
            it["origin"] = sorted(set(it.get("origin", [])) | {slug})

        scored = ai_score(candidates, profile, api_key=api_key, model=tagger_model)
        all_health.append(scored["health"])
        for it in candidates:
            s = scored["scores"].get(it["id"])
            if s:
                it["_ai_relevance"] = s["relevance"]
                it["_ai_reason"] = s["reason"]

        for it in deduped:
            corpus.upsert(it)

        if not candidates:
            print(f"{slug}: 0 new candidates, no review file written")
            continue

        review_dir = REPO_ROOT / "topics" / slug / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        parts = issue_bodies(candidates, profile, run_label=run_label)
        for i, (_suffix, body) in enumerate(parts, start=1):
            review_path = review_dir / (f"{run_label}.md" if len(parts) == 1 else f"{run_label}-part{i}.md")
            review_path.write_text(body, encoding="utf-8")
            print(f"{slug}: {len(candidates)} candidates -> {review_path.relative_to(REPO_ROOT)}"
                  + (f" (part {i}/{len(parts)})" if len(parts) > 1 else ""))

    corpus.save()

    previous_health = load_health(DATA_DIR / "health" / "latest.json")
    health_doc = aggregate_health(all_health, previous=previous_health, run_label=run_label)
    save_health(DATA_DIR / "health" / f"{run_label}.json", health_doc)
    save_health(DATA_DIR / "health" / "latest.json", health_doc)
    print(f"health: {health_doc['stats']['sources_ok']}/{health_doc['stats']['sources_total']} sources ok, "
          f"{health_doc['stats']['items_total']} items total")
    return 0


def cmd_publish(args) -> int:
    profile = load_profile(args.topic)
    body = Path(args.issue_body_file).read_text(encoding="utf-8")
    parsed = parse_review(body)

    decisions = DecisionStore(DATA_DIR / "decisions" / f"{args.topic}.jsonl")
    for item_id in parsed["all"]:
        decision = "accepted" if item_id in parsed["accepted"] else "rejected"
        decisions.record(item_id, decision, run=args.run, featured=item_id in parsed["featured"])
    decisions.save()
    print(f"{args.topic}: {len(parsed['accepted'])} accepted, {len(parsed['all']) - len(parsed['accepted'])} rejected")

    result = build_mod.build()
    print(f"site rebuilt: {result['pages']} pages for {result['topics']} topics")
    return 0


def cmd_build(args) -> int:
    result = build_mod.build()
    print(f"site rebuilt: {result['pages']} pages for {result['topics']} topics")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_harvest = sub.add_parser("harvest", help="run connectors, write review-issue markdown per topic")
    p_harvest.add_argument("--topic", help="harvest only this topic (default: all active topics)")
    p_harvest.add_argument("--skip-gdelt", action="store_true", help="skip GDELT (useful while rate-limited)")
    p_harvest.set_defaults(func=cmd_harvest)

    p_publish = sub.add_parser("publish", help="parse a closed review issue into decisions, rebuild the site")
    p_publish.add_argument("--topic", required=True)
    p_publish.add_argument("--issue-body-file", required=True)
    p_publish.add_argument("--run", required=True)
    p_publish.set_defaults(func=cmd_publish)

    p_build = sub.add_parser("build", help="re-render the site from current data/")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
