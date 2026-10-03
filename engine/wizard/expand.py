"""Term-expansion helper for the new-topic wizard's "Expand" step (seed
keywords -> candidate related terms).

This does the mechanical legwork only — sample OpenAlex for the seed
terms, count what concepts/keywords show up often — not the judgment.
Per the build brief's design, the wizard "runs inside a Claude Code
session so a model is available": picking which candidates to keep, and
asking Kevin things like "which sub-aspects?" or "which disciplinary
angles?", is a live conversation between Kevin and whichever session is
handling his new-topic request (see CLAUDE.md, "Handling a new-topic
request"), not something this script decides on its own.
"""
from __future__ import annotations

from collections import Counter

from engine.connectors.openalex import API_URL, make_session


# OpenAlex's `concepts` taxonomy is leveled 0 (broadest field, e.g.
# "Economics", "Biology") to 5+ (narrowest). Broad-level concepts get
# attached to nearly every work regardless of real relevance — confirmed
# live, 2026-10-03, seeding "mould" + "housing UK": the top raw-count hits
# were generic fields like "Economics"/"Biology"/"Political science"
# (mould is polysemous — fungi, injection-casting, cheese-making — and
# OpenAlex tags broad fields onto all of those alike), while the genuinely
# useful terms ("housing policy", "damp housing", "Cladosporium",
# "UK housing market") were buried further down. Filtering to level >= 2
# and a minimum per-work concept score removes that noise.
MIN_CONCEPT_LEVEL = 2
MIN_SCORE = 0.3


def expand_seed_terms(
    seeds: list,
    *,
    contact_email: str,
    sample_size: int = 100,
    per_page: int = 50,
    top_n: int = 30,
) -> dict:
    """Sample OpenAlex results for each of `seeds`, return candidate related
    terms ranked by total relevance score (not raw frequency — see
    MIN_CONCEPT_LEVEL above for why frequency alone is noisy), each with one
    example title so a human can sanity-check what it's picking up before
    approving it.

    Returns {"seeds": [...], "sampled_titles": int, "candidates": [{"term",
    "count", "total_score", "example_title"}, ...]}.
    """
    if not seeds:
        raise ValueError("expand_seed_terms needs at least one seed term")

    session = make_session(contact_email)
    seed_lower = {s.lower() for s in seeds}
    term_scores: Counter = Counter()
    term_counts: Counter = Counter()
    term_examples: dict = {}
    sampled_titles = 0

    for seed in seeds:
        fetched = 0
        cursor = "*"
        while fetched < sample_size:
            resp = session.get(API_URL, params={"search": seed, "per-page": per_page, "cursor": cursor}, timeout=20)
            if resp.status_code != 200:
                break
            payload = resp.json()
            results = payload.get("results", [])
            if not results:
                break
            for work in results:
                title = work.get("title") or work.get("display_name") or ""
                if title:
                    sampled_titles += 1

                hits = []
                for concept in work.get("concepts", []) or []:
                    name = concept.get("display_name")
                    level = concept.get("level", 0)
                    score = concept.get("score", 0) or 0
                    if name and level >= MIN_CONCEPT_LEVEL and score >= MIN_SCORE:
                        hits.append((name, score))
                for kw in work.get("keywords", []) or []:
                    if not isinstance(kw, dict):
                        continue
                    name = kw.get("display_name")
                    score = kw.get("score", 0) or 0
                    if name and score >= MIN_SCORE:
                        hits.append((name, score))

                for name, score in hits:
                    if name.lower() in seed_lower:
                        continue
                    term_scores[name] += score
                    term_counts[name] += 1
                    term_examples.setdefault(name, title)
            fetched += len(results)
            cursor = (payload.get("meta") or {}).get("next_cursor")
            if not cursor:
                break

    candidates = [
        {"term": term, "count": term_counts[term], "total_score": round(total_score, 2), "example_title": term_examples.get(term, "")}
        for term, total_score in term_scores.most_common(top_n)
    ]
    return {"seeds": list(seeds), "sampled_titles": sampled_titles, "candidates": candidates}
