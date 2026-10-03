"""CLI entry points: harvest, backfill, publish, build.

`python -m engine harvest` — run connectors once for the union of every
active topic's queries, score against each topic, write a review-issue
markdown file per topic for the Action to open as a GitHub issue.

`python -m engine backfill --topic X --years-back N` — one-time historical
pull further back than the regular 12-month window, scholarship only (see
engine/pipeline/backfill.py for why). Not part of the regular cadence.

`python -m engine publish --topic X --issue-body-file F --run R` — parse a
closed review issue back into decisions, update the corpus, rebuild the site.

`python -m engine build` — just re-render the site from current data/.

`python -m engine wizard-expand --seed "term1" "term2"` — sample OpenAlex
for the seed terms, print candidate related terms ranked by how often they
co-occur. A research aid for a live session working a new-topic request
(see CLAUDE.md, "Handling a new-topic request") — it doesn't decide
anything or write any files itself.
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
from engine.pipeline.backfill import (
    DEFAULT_CITATIONS_PER_MONTH,
    DEFAULT_GRACE_PERIOD_DAYS,
    backfill_date_from,
    run_citation_prefilter,
)
from engine.pipeline.corpus import Corpus, DecisionStore
from engine.pipeline.dedupe import dedupe
from engine.pipeline.health import aggregate_health, load_health, save_health
from engine.pipeline.profile import REPO_ROOT, list_topics, load_profile, outlets_for_topic
from engine.pipeline.review import issue_bodies, parse_review
from engine.pipeline.score import ai_score, run_keyword_gate

DATA_DIR = REPO_ROOT / "data"


def _run_label(cadence_hint: str = "") -> str:
    return date.today().isoformat()


def _clear_review_dir(slug: str) -> Path:
    """See the long comment in cmd_harvest for why this must run
    unconditionally, before any check for whether there's anything new to
    write — a real bug (2026-10-03) came from skipping it when there wasn't."""
    review_dir = REPO_ROOT / "topics" / slug / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    for stale in review_dir.glob("*.md"):
        stale.unlink()
    return review_dir


def _write_review_files(slug: str, profile: dict, candidates: list, run_label: str, review_dir: Path) -> None:
    if not candidates:
        print(f"{slug}: 0 candidates, no review file written")
        return
    parts = issue_bodies(candidates, profile, run_label=run_label)
    for i, (_suffix, body) in enumerate(parts, start=1):
        review_path = review_dir / (f"{run_label}.md" if len(parts) == 1 else f"{run_label}-part{i}.md")
        review_path.write_text(body, encoding="utf-8")
        print(f"{slug}: {len(candidates)} candidates -> {review_path.relative_to(REPO_ROOT)}"
              + (f" (part {i}/{len(parts)})" if len(parts) > 1 else ""))


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
    # os.environ.get(key, default) only falls back when the key is *absent*.
    # harvest.yml always sets TAGGER_MODEL (to "${{ vars.TAGGER_MODEL }}"),
    # which GitHub Actions renders as an empty string when the repo variable
    # doesn't exist, rather than omitting the env var — so `.get` alone
    # returns "" instead of the intended default. `or` catches that case too.
    tagger_model = os.environ.get("TAGGER_MODEL") or "claude-haiku-4-5"

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
                it["_ai_quality"] = s["quality"]
                it["_ai_reason"] = s["reason"]
                it["_ai_tags"] = s.get("tags", [])

        for it in deduped:
            corpus.upsert(it)

        # Clear old review files *before* the empty-candidates check, not
        # after — these are transient hand-off files for `gh issue create`
        # (the issue itself is the permanent record; nothing re-reads this
        # file afterwards), so a file left over from an earlier run must
        # never sit here for harvest.yml's `topics/*/review/*.md` glob to
        # pick up again. Two real bugs found live, both from exactly this
        # directory not being cleared unconditionally:
        #   - 2026-10-03, run 2: an oversized file from a run that failed
        #     at issue-creation was still present on the next run and
        #     failed `gh issue create` again, even though that run's own
        #     files were fine. Fix (first pass): clear before writing.
        #   - 2026-10-03, run 4: that fix only cleared the directory when
        #     there *were* new candidates — a run that found none (e.g.
        #     because every harvested item was already decided) left the
        #     PREVIOUS run's already-published files sitting there, and
        #     the next run's issue-creation step re-opened them as
        #     duplicate issues (#3, #4, closed as duplicates of #1/#2).
        #     Fix: clear unconditionally, before the candidates check.
        review_dir = _clear_review_dir(slug)
        _write_review_files(slug, profile, candidates, run_label, review_dir)

    corpus.save()

    previous_health = load_health(DATA_DIR / "health" / "latest.json")
    health_doc = aggregate_health(all_health, previous=previous_health, run_label=run_label)
    save_health(DATA_DIR / "health" / f"{run_label}.json", health_doc)
    save_health(DATA_DIR / "health" / "latest.json", health_doc)
    print(f"health: {health_doc['stats']['sources_ok']}/{health_doc['stats']['sources_total']} sources ok, "
          f"{health_doc['stats']['items_total']} items total")
    return 0


def cmd_backfill(args) -> int:
    """One-time historical pull for a single topic, further back than the
    regular 12-month window. Scholarship only (OpenAlex) — see
    engine/pipeline/backfill.py for why, and for the age-weighted citation
    pre-filter this applies before AI scoring to keep a multi-year pull
    tractable without penalizing recent work for not having citations yet.
    """
    profile = load_profile(args.topic)
    contact_email = os.environ.get("CONTACT_EMAIL", "")
    if not contact_email:
        print("CONTACT_EMAIL not set — required for the OpenAlex polite pool", file=sys.stderr)
        return 1

    queries = (profile.get("connectors", {}).get("openalex", {}) or {}).get("queries", [])
    if not queries:
        print(f"{args.topic}: no connectors.openalex.queries configured, nothing to backfill", file=sys.stderr)
        return 1

    today = date.today()
    date_from = backfill_date_from(args.years_back, today=today)
    run_label = f"backfill-{args.years_back}y-{today.isoformat()}"
    print(f"backfilling {args.topic} from {date_from} ({args.years_back} year(s) back, max {args.max_pages} pages/query)")

    items, health = harvest_openalex(
        queries, contact_email=contact_email, date_from=date_from, max_pages=args.max_pages
    )
    print(f"harvested {len(items)} raw items")

    corpus = Corpus(DATA_DIR / "items.jsonl")
    result = dedupe(items)
    deduped = result["items"]
    print(f"-> {len(deduped)} after dedupe (rate {result['stats']['duplicate_rate']:.1%})")

    decisions = DecisionStore(DATA_DIR / "decisions" / f"{args.topic}.jsonl")
    already_decided = decisions.decided_ids()
    survivors, _rejected = run_keyword_gate(deduped, profile)
    candidates = [it for it in survivors if it["id"] not in already_decided]
    print(f"-> {len(candidates)} pass the keyword gate and aren't already decided")

    candidates, dropped = run_citation_prefilter(
        candidates, today=today, grace_period_days=args.grace_period_days, citations_per_month=args.citations_per_month
    )
    print(f"-> {len(candidates)} pass the age-weighted citation pre-filter ({len(dropped)} dropped)")
    for it in candidates:
        it["origin"] = sorted(set(it.get("origin", [])) | {args.topic})

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    tagger_model = os.environ.get("TAGGER_MODEL") or "claude-haiku-4-5"
    scored = ai_score(candidates, profile, api_key=api_key, model=tagger_model)
    health.append(scored["health"])
    for it in candidates:
        s = scored["scores"].get(it["id"])
        if s:
            it["_ai_relevance"] = s["relevance"]
            it["_ai_quality"] = s["quality"]
            it["_ai_reason"] = s["reason"]
            it["_ai_tags"] = s.get("tags", [])

    for it in deduped:
        corpus.upsert(it)
    corpus.save()

    review_dir = _clear_review_dir(args.topic)
    _write_review_files(args.topic, profile, candidates, run_label, review_dir)

    # Dated health file only — never overwrite data/health/latest.json
    # here. latest.json is what the site's health page shows as current
    # source status; a backfill only touches OpenAlex, so writing it there
    # would make GDELT/RSS look like they'd vanished rather than just not
    # being part of this run.
    save_health(DATA_DIR / "health" / f"{run_label}.json", aggregate_health(health, previous=None, run_label=run_label))
    return 0


def cmd_publish(args) -> int:
    profile = load_profile(args.topic)
    body = Path(args.issue_body_file).read_text(encoding="utf-8")
    parsed = parse_review(body)

    decisions = DecisionStore(DATA_DIR / "decisions" / f"{args.topic}.jsonl")
    for item_id in parsed["all"]:
        decision = "accepted" if item_id in parsed["accepted"] else "rejected"
        item_meta = parsed["meta"].get(item_id, {})
        decisions.record(
            item_id, decision, run=args.run, featured=item_id in parsed["featured"],
            quality=item_meta.get("quality"), relevance=item_meta.get("relevance"),
            tags=item_meta.get("tags"),
        )
    decisions.save()
    print(f"{args.topic}: {len(parsed['accepted'])} accepted, {len(parsed['all']) - len(parsed['accepted'])} rejected")

    result = build_mod.build()
    print(f"site rebuilt: {result['pages']} pages for {result['topics']} topics")
    return 0


def cmd_build(args) -> int:
    result = build_mod.build()
    print(f"site rebuilt: {result['pages']} pages for {result['topics']} topics")
    return 0


def cmd_wizard_expand(args) -> int:
    from engine.wizard.expand import expand_seed_terms

    contact_email = os.environ.get("CONTACT_EMAIL", "")
    if not contact_email:
        print("CONTACT_EMAIL not set — required for the OpenAlex polite pool", file=sys.stderr)
        return 1

    result = expand_seed_terms(args.seed, contact_email=contact_email, sample_size=args.sample_size)
    print(f"seeds: {result['seeds']}")
    print(f"sampled {result['sampled_titles']} titles\n")
    print(f"{'term':<40} {'score':>6} {'count':>6}  example")
    for c in result["candidates"]:
        print(f"{c['term']:<40} {c['total_score']:>6} {c['count']:>6}  {c['example_title'][:65]}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_harvest = sub.add_parser("harvest", help="run connectors, write review-issue markdown per topic")
    p_harvest.add_argument("--topic", help="harvest only this topic (default: all active topics)")
    p_harvest.add_argument("--skip-gdelt", action="store_true", help="skip GDELT (useful while rate-limited)")
    p_harvest.set_defaults(func=cmd_harvest)

    p_backfill = sub.add_parser("backfill", help="one-time historical pull beyond the normal 12-month window (scholarship only)")
    p_backfill.add_argument("--topic", required=True)
    p_backfill.add_argument("--years-back", type=int, default=1, help="how far back to pull (default: 1 year)")
    p_backfill.add_argument("--max-pages", type=int, default=20, help="OpenAlex pages per query, 50 items/page (default: 20)")
    p_backfill.add_argument("--grace-period-days", type=int, default=DEFAULT_GRACE_PERIOD_DAYS,
                             help=f"items this recent always pass the citation pre-filter regardless of citations (default: {DEFAULT_GRACE_PERIOD_DAYS})")
    p_backfill.add_argument("--citations-per-month", type=float, default=DEFAULT_CITATIONS_PER_MONTH,
                             help=f"required citations grow by this much per month beyond the grace period (default: {DEFAULT_CITATIONS_PER_MONTH})")
    p_backfill.set_defaults(func=cmd_backfill)

    p_publish = sub.add_parser("publish", help="parse a closed review issue into decisions, rebuild the site")
    p_publish.add_argument("--topic", required=True)
    p_publish.add_argument("--issue-body-file", required=True)
    p_publish.add_argument("--run", required=True)
    p_publish.set_defaults(func=cmd_publish)

    p_build = sub.add_parser("build", help="re-render the site from current data/")
    p_build.set_defaults(func=cmd_build)

    p_wizard = sub.add_parser("wizard-expand", help="sample OpenAlex for seed terms, print candidate related terms")
    p_wizard.add_argument("--seed", nargs="+", required=True, help="one or more seed keywords")
    p_wizard.add_argument("--sample-size", type=int, default=100)
    p_wizard.set_defaults(func=cmd_wizard_expand)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
