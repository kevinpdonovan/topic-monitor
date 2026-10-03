"""Two-stage relevance scoring, per topic.

Stage 1 (always runs, free): a keyword/term gate against the topic
profile — ported from insubordinate-terminal's Scorer.assess() approach,
generalized so section-specific thresholds come from the profile instead of
being hardcoded per repo.

Stage 2 (optional, costs money): a Claude API batch call on stage-1
survivors, returning a 0-3 relevance score, a quality tier, tags and a
one-line reason — same JSON-array-over-a-batch-of-25 contract both
reference repos use for relevance; the quality tier is new (added
2026-10-03, at Kevin's request — see _SYSTEM_PROMPT).

NOTE on the build brief's stage 1 design ("embedding similarity against the
topic's seed text and accepted items"): not implemented here. Doing it
properly means picking and paying for an embeddings provider (Claude has no
embeddings endpoint — would mean adding e.g. Voyage AI), which wasn't part
of the API decision Kevin already made. The keyword/term gate below is the
reference repos' proven zero-marginal-cost substitute and is enough to hit
Phase 1's criteria; swap in real embedding similarity later if the keyword
gate's false-negative rate turns out to matter once we have accepted/
rejected items to evaluate it against (natural Phase 3 feedback-loop work).
"""
from __future__ import annotations

import json
import re

from engine.pipeline.profile import load_registry

BATCH_SIZE = 25
QUALITY_TIERS = ("high", "medium", "low")


def _text_blob(item: dict) -> str:
    return " ".join(filter(None, [item.get("title", ""), item.get("abstract", ""), item.get("venue", "")])).lower()


def keyword_gate(item: dict, profile: dict) -> dict:
    """Cheap pre-filter. Returns {passed, matched_terms, reason}."""
    blob = _text_blob(item)
    lang = item.get("language", "en")

    exclusions = [e.lower() for e in profile.get("exclusions", [])]
    for term in exclusions:
        if term in blob:
            return {"passed": False, "matched_terms": [], "reason": f"excluded: matched {term!r}"}

    keywords = profile.get("keywords", [])
    matched = []
    for kw in keywords:
        term = kw["term"].lower() if isinstance(kw, dict) else str(kw).lower()
        kw_lang = kw.get("language", "en") if isinstance(kw, dict) else "en"
        if kw_lang != lang and kw_lang != "en":
            continue
        if term in blob:
            matched.append(term)

    orgs = [o.lower() for o in profile.get("organisation_names", [])]
    org_hit = item.get("organisation", "").lower() in orgs if orgs else False

    passed = bool(matched) or org_hit
    reason = f"matched {matched}" if matched else ("organisation match" if org_hit else "no keyword/organisation match")
    return {"passed": passed, "matched_terms": matched, "reason": reason}


def run_keyword_gate(items: list, profile: dict) -> tuple:
    """Returns (survivors, rejected) — each item gets a `_gate` key with the result."""
    survivors, rejected = [], []
    for item in items:
        gate = keyword_gate(item, profile)
        item = dict(item)
        item["_gate"] = gate
        (survivors if gate["passed"] else rejected).append(item)
    return survivors, rejected


# Quality rubric per Kevin, 2026-10-03: explicitly NOT journal
# prestige/h-index/citations. See registry/quality_signals.yaml for why the
# heterodox/Global South source list is asymmetric (no equivalent
# "mainstream prestige" list) and what it's for.
_SYSTEM_PROMPT = """You rate items for a research monitor on two independent axes: relevance to the topic, and quality.

RELEVANCE (0-3): 0 = not relevant, 1 = tangential, 2 = relevant, 3 = central to the topic.

QUALITY ("high", "medium", or "low") — judge substance, not prestige:
- Do NOT infer quality from journal impact factor, h-index, citation counts, or publisher name recognition.
- Value empirical work with real data and evidence, especially well-executed case studies.
- Also value high-quality theoretical or conceptual contributions, even without new empirical data.
- Give "systematic reviews" and "literature reviews" a HIGH BAR: most are "medium" at best — reserve "high"
  for ones that are genuinely field-defining, not merely well-organized summaries. Default to skepticism here.
- Rate "low" work that has little new data or evidence AND no serious theoretical/conceptual contribution —
  e.g. press-release-style reporting, superficial commentary, restating conventional wisdom without rigor.
- Actively value heterodox and anti-systemic political economy perspectives (e.g. dependency theory,
  world-systems analysis, structuralist and agrarian political economy) and work from peripheral/Global South
  institutions. Do not under-rate these for being less mainstream or less familiar — judge them on the same
  rigor standard as anything else. A list of known-rigorous heterodox/Global South sources is provided below
  as context (not exhaustive, not gatekeeping) specifically to counter the tendency to under-rate unfamiliar
  venues relative to prestigious Global-North ones.

Reply with ONLY a JSON array, one object per item, no prose:
[{"id": "...", "relevance": 0, "quality": "high", "tags": ["..."], "reason": "one short sentence"}, ...]"""


def _quality_context(registry: dict | None = None) -> str:
    registry = registry if registry is not None else load_registry("quality_signals")
    sources = registry.get("heterodox_and_global_south_sources", [])
    if not sources:
        return ""
    return "Known-rigorous heterodox/Global South sources (see above — not exhaustive): " + "; ".join(sources)


def _batches(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def parse_score_response(text: str) -> list:
    """Extract the JSON array of {id, relevance, quality, tags, reason} rows
    from a raw model response. Pulled out of ai_score() so it's testable
    without the anthropic package or a network call — ai_score() only
    orchestrates the API round-trip.
    """
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    parsed = json.loads(match.group(0))
    rows = []
    for row in parsed:
        if "id" not in row:
            continue
        quality = row.get("quality")
        if quality not in QUALITY_TIERS:
            quality = None
        rows.append(
            {
                "id": row["id"],
                "relevance": row.get("relevance", 0),
                "quality": quality,
                "tags": row.get("tags", []),
                "reason": row.get("reason", ""),
            }
        )
    return rows


def ai_score(items: list, profile: dict, *, api_key: str, model: str = "claude-haiku-4-5") -> dict:
    """Scores `items` (already stage-1 survivors) via the Claude API.

    Returns {"scores": {id: {relevance, quality, tags, reason}}, "health": {...}}.
    If api_key is falsy, returns an empty result with a health note rather
    than raising — AI scoring is an enhancement, not a hard dependency.
    """
    if not api_key:
        return {"scores": {}, "health": {"source": "ai_score", "ok": False, "count": 0, "note": "no ANTHROPIC_API_KEY set, AI scoring skipped"}}

    import anthropic  # lazy import: not a hard dependency for callers that never score

    client = anthropic.Anthropic(api_key=api_key)
    seed_text = (profile.get("relevance", {}) or {}).get("seed_text", profile.get("description", ""))
    quality_context = _quality_context()

    scores: dict = {}
    scored_count = 0
    note = ""
    ok = True
    try:
        for batch in _batches(items, BATCH_SIZE):
            payload = [
                {"id": it["id"], "title": it["title"], "abstract": it.get("abstract", "")[:600], "venue": it.get("venue", ""), "organisation": it.get("organisation", "")}
                for it in batch
            ]
            user_prompt = (
                f"Topic: {profile.get('title')}\nWhat this topic covers: {seed_text}\n\n"
                f"{quality_context}\n\nItems:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            resp = client.messages.create(
                model=model,
                max_tokens=2500,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            for row in parse_score_response(text):
                scores[row["id"]] = {k: v for k, v in row.items() if k != "id"}
                scored_count += 1
    except Exception as exc:
        ok = False
        note = str(exc)

    return {"scores": scores, "health": {"source": "ai_score", "ok": ok, "count": scored_count, "note": note}}
