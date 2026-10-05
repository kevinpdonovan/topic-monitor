"""Deduplication: exact id merge, then near-duplicate scholarly versions,
then syndicated-news clustering.

Ported from insubordinate-terminal/soft-currency-observatory's dedupe.py
(near-identical in both — see CLAUDE.md). One change: work_key() is now
computed unconditionally for every item before merge_versions runs, instead
of some code path being able to skip assigning it. The reference repos' bug
(reproduced directly in insubordinate-terminal/data/runs/2026-W40/
candidates.json: two Zenodo copies of the same work, both *missing*
work_key, reached the review queue as separate checkboxes) was exactly that
— a code path that should have set work_key and silently didn't. Computing
it here, always, removes that whole class of bug rather than patching the
one call site. (An earlier version of this fix added an assert that
work_key() was always non-empty for a titled item — that turned out to be
wrong, not just defensive: a non-Latin-script title legitimately produces
no tokens under this module's ASCII-only tokenizer, and the assert crashed
the first live harvest run on exactly that case. See merge_versions().)
"""
from __future__ import annotations

import re

STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "of", "on", "or", "that", "the", "their", "this",
    "to", "towards", "with", "within",
}

# Prefer the record most useful to a reader: a published version of record
# over a preprint, a report over a dataset, etc.
TYPE_RANK = {
    "article": 3, "chapter": 3, "book": 3,
    "report": 2, "policy_document": 2, "working_paper": 1,
    "news": 1, "discourse": 0, "podcast": 1,
}


def title_tokens(title: str) -> set:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in STOP and len(w) > 1}


def title_key(title: str) -> str:
    return " ".join(sorted(title_tokens(title)))


def surname(authors: list) -> str:
    """Last name of the first author, used as the author half of work_key.

    Trailing publication metadata is stripped first. Some records cram it
    into the author field — found live 2026-10-05, where two copies of the
    same Italian paper failed to merge because one listed the author as
    "Giuseppe La Rosa" and the other as "Giuseppe La Rosa - Pubblicato in
    Amministrativ@mente 3/2024", making the naive last-token surname
    "3/2024". Only the separator-trailing junk is dropped, so this can
    never merge two genuinely different authors; it just stops a malformed
    field from splitting one.
    """
    if not authors:
        return ""
    first = re.split(r"\s+[-–—]\s+|\s*\(", authors[0].strip())[0].strip()
    return first.split()[-1].lower() if first else ""


def work_key(item: dict) -> str:
    """Identity for 'the same intellectual work', independent of which DOI/
    URL a particular upload or version got. Always computable — falls back
    to title-only if there's no author."""
    tk = title_key(item.get("title", ""))
    if not tk:
        return ""
    return f"{tk}|{surname(item.get('authors', []))}"


def version_score(item: dict) -> tuple:
    return (
        TYPE_RANK.get(item.get("source_type"), 0),
        1 if item.get("doi") else 0,
        len(item.get("abstract", "")),
        1 if item.get("pdf_url") else 0,
    )


def _merge_into(primary: dict, extra: dict) -> dict:
    primary = dict(primary)
    primary["origin"] = sorted(set(primary.get("origin", [])) | set(extra.get("origin", [])))
    for field in ("abstract", "pdf_url", "venue", "organisation", "doi", "isbn"):
        if not primary.get(field) and extra.get(field):
            primary[field] = extra[field]
    merged_extra = dict(extra.get("extra", {}))
    merged_extra.update(primary.get("extra", {}))
    merged_extra["merged_ids"] = sorted(set(merged_extra.get("merged_ids", [])) | {extra["id"]})
    primary["extra"] = merged_extra
    return primary


def merge_versions(items: list) -> tuple:
    """Collapse same-work different-DOI/URL duplicates. Returns (kept, n_merged).

    An item whose title tokenizes to nothing (title_tokens() uses an
    ASCII-only regex, so a title entirely in a non-Latin script — e.g. a
    Chinese-language e-CNY paper — has no tokens) falls through to
    `singles` below rather than being dropped or raising: it just can't be
    version-merged by this heuristic, which is a real limitation (found
    live, 2026-10-03, on the first production harvest run) but not a bug —
    unlike the Zenodo gap this module exists to fix, there's no code path
    here that *should* produce a work_key and silently doesn't.
    """
    groups: dict = {}
    singles = []
    for item in items:
        wk = work_key(item)
        if not wk:
            singles.append(item)
            continue
        groups.setdefault(wk, []).append(item)

    kept = list(singles)
    merged_count = 0
    for wk, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        group_sorted = sorted(group, key=version_score, reverse=True)
        primary = group_sorted[0]
        for extra in group_sorted[1:]:
            primary = _merge_into(primary, extra)
            merged_count += 1
        kept.append(primary)
    return kept, merged_count


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_news(items: list, threshold: float = 0.6) -> tuple:
    """Group syndicated news/discourse items by title-token Jaccard similarity,
    keep the richest copy. Returns (kept, n_merged)."""
    news = [i for i in items if i.get("source_type") in ("news", "discourse")]
    other = [i for i in items if i.get("source_type") not in ("news", "discourse")]
    tokens = {i["id"]: title_tokens(i["title"]) for i in news}

    clusters = []
    assigned = set()
    for item in news:
        if item["id"] in assigned:
            continue
        cluster = [item]
        assigned.add(item["id"])
        for other_item in news:
            if other_item["id"] in assigned:
                continue
            if _jaccard(tokens[item["id"]], tokens[other_item["id"]]) >= threshold:
                cluster.append(other_item)
                assigned.add(other_item["id"])
        clusters.append(cluster)

    kept = list(other)
    merged_count = 0
    for cluster in clusters:
        if len(cluster) == 1:
            kept.append(cluster[0])
            continue
        cluster_sorted = sorted(cluster, key=version_score, reverse=True)
        primary = cluster_sorted[0]
        for extra in cluster_sorted[1:]:
            primary = _merge_into(primary, extra)
            merged_count += 1
        kept.append(primary)
    return kept, merged_count


def dedupe(items: list, corpus=None) -> dict:
    """Full pipeline: exact-id merge, then scholarly version merge, then news
    clustering, then drop anything already in `corpus` (seen in a prior run).

    Returns {"items": [...], "stats": {"input", "output", "exact_merged",
    "version_merged", "news_merged", "already_seen", "duplicate_rate"}}.
    """
    input_count = len(items)

    by_id: dict = {}
    exact_merged = 0
    for item in items:
        if item["id"] in by_id:
            by_id[item["id"]] = _merge_into(by_id[item["id"]], item)
            exact_merged += 1
        else:
            by_id[item["id"]] = item
    items = list(by_id.values())

    items, version_merged = merge_versions(items)
    items, news_merged = cluster_news(items)

    already_seen = 0
    if corpus is not None:
        fresh = []
        for item in items:
            if item["id"] in corpus:
                already_seen += 1
            else:
                fresh.append(item)
        items = fresh

    total_dupes = exact_merged + version_merged + news_merged
    duplicate_rate = total_dupes / input_count if input_count else 0.0

    return {
        "items": items,
        "stats": {
            "input": input_count,
            "output": len(items),
            "exact_merged": exact_merged,
            "version_merged": version_merged,
            "news_merged": news_merged,
            "already_seen": already_seen,
            "duplicate_rate": round(duplicate_rate, 4),
        },
    }
