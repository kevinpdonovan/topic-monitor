"""Two-stage relevance scoring, per topic.

Stage 1 (always runs, free): a keyword/term gate against the topic
profile — ported from insubordinate-terminal's Scorer.assess() approach,
generalized so section-specific thresholds come from the profile instead of
being hardcoded per repo.

Stage 2 (optional, costs money): a Claude API batch call on stage-1
survivors, returning a 0-3 relevance score, tags and a one-line reason —
same JSON-array-over-a-batch-of-25 contract both reference repos use.

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

BATCH_SIZE = 25


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


_SYSTEM_PROMPT = """You rate how relevant each item is to a research monitor's topic.
Score 0-3: 0 = not relevant, 1 = tangential, 2 = relevant, 3 = central to the topic.
Reply with ONLY a JSON array, one object per item, no prose:
[{"id": "...", "relevance": 0, "tags": ["..."], "reason": "one short sentence"}, ...]"""


def _batches(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def ai_score(items: list, profile: dict, *, api_key: str, model: str = "claude-haiku-4-5") -> dict:
    """Scores `items` (already stage-1 survivors) via the Claude API.

    Returns {"scores": {id: {relevance, tags, reason}}, "health": {...}}.
    If api_key is falsy, returns an empty result with a health note rather
    than raising — AI scoring is an enhancement, not a hard dependency.
    """
    if not api_key:
        return {"scores": {}, "health": {"source": "ai_score", "ok": False, "count": 0, "note": "no ANTHROPIC_API_KEY set, AI scoring skipped"}}

    import anthropic  # lazy import: not a hard dependency for callers that never score

    client = anthropic.Anthropic(api_key=api_key)
    seed_text = (profile.get("relevance", {}) or {}).get("seed_text", profile.get("description", ""))

    scores: dict = {}
    scored_count = 0
    note = ""
    ok = True
    try:
        for batch in _batches(items, BATCH_SIZE):
            payload = [
                {"id": it["id"], "title": it["title"], "abstract": it.get("abstract", "")[:600], "venue": it.get("venue", "")}
                for it in batch
            ]
            user_prompt = f"Topic: {profile.get('title')}\nWhat this topic covers: {seed_text}\n\nItems:\n{json.dumps(payload, ensure_ascii=False)}"
            resp = client.messages.create(
                model=model,
                max_tokens=2000,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                continue
            parsed = json.loads(match.group(0))
            for row in parsed:
                if "id" in row:
                    scores[row["id"]] = {
                        "relevance": row.get("relevance", 0),
                        "tags": row.get("tags", []),
                        "reason": row.get("reason", ""),
                    }
                    scored_count += 1
    except Exception as exc:
        ok = False
        note = str(exc)

    return {"scores": scores, "health": {"source": "ai_score", "ok": ok, "count": scored_count, "note": note}}
