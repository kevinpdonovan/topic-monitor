"""Review queue as a GitHub issue: render a checklist, parse the closed issue
body back into accept/reject decisions. Same design both reference repos
use (issue-as-queue, HTML-comment-encoded id, checkbox state = approval) —
this is the best-proven part of either repo, kept close to as-is.
"""
from __future__ import annotations

import re

SOURCE_TYPE_HEADINGS = [
    ("article", "Research articles"),
    ("chapter", "Book chapters"),
    ("book", "Books"),
    ("working_paper", "Working papers"),
    ("report", "Reports and grey literature"),
    ("policy_document", "Policy and official documents"),
    ("news", "News"),
    ("discourse", "Discourse"),
    ("podcast", "Podcasts"),
]

LINE_RX = re.compile(
    r"^-\s*\[(?P<tick>[ xX])\]\s*(?P<star>★\s*)?\[(?P<title>[^\]]*)\]\((?P<url>[^)]*)\).*?<!--id:(?P<id>[0-9a-f]{10})-->\s*$",
    re.MULTILINE,
)


def _pretick(item: dict) -> bool:
    ai = item.get("_ai_relevance")
    if ai is not None:
        return ai >= 2
    gate = item.get("_gate", {})
    return bool(gate.get("passed")) and len(gate.get("matched_terms", [])) >= 2


def _line(item: dict) -> str:
    tick = "x" if _pretick(item) else " "
    ai = item.get("_ai_relevance")
    star = "★ " if ai == 3 else ""
    meta_bits = [b for b in [item.get("venue"), item.get("date"), item.get("organisation")] if b]
    meta = " · ".join(meta_bits)
    badge = f" `relevance:{ai}`" if ai is not None else ""
    reason = item.get("_ai_reason") or item.get("_gate", {}).get("reason", "")
    reason_bit = f" — _{reason}_" if reason else ""
    url = item.get("url") or item.get("pdf_url") or ""
    return f"- [{tick}] {star}[{item['title']}]({url}) · {meta}{badge}{reason_bit} <!--id:{item['id']}-->"


def issue_body(items: list, profile: dict, *, run_label: str) -> str:
    """Render the full review-issue markdown, grouped by source_type."""
    by_type: dict = {}
    for item in items:
        by_type.setdefault(item.get("source_type", "article"), []).append(item)

    lines = [
        f"# {profile.get('title', profile.get('slug'))} — review for {run_label}",
        "",
        f"{len(items)} candidate items. Tick the ones to accept, untick the rest, "
        "then close this issue to publish.",
        "",
    ]
    for source_type, heading in SOURCE_TYPE_HEADINGS:
        group = by_type.get(source_type, [])
        if not group:
            continue
        group.sort(key=lambda it: it.get("date") or "", reverse=True)
        group.sort(key=lambda it: it.get("_ai_relevance") or 0, reverse=True)
        lines.append(f"## {heading} ({len(group)})")
        lines.append("")
        lines.extend(_line(it) for it in group)
        lines.append("")
    return "\n".join(lines)


def parse_review(body: str) -> dict:
    """Parse a (closed) review issue body.

    Returns {"accepted": set, "featured": set, "all": set} — `all` is every
    item id that appeared in the issue (ticked or not), so the caller can
    record explicit rejections for anything left unticked, not just accepts.
    """
    accepted, featured, all_ids = set(), set(), set()
    for match in LINE_RX.finditer(body):
        item_id = match.group("id")
        all_ids.add(item_id)
        if match.group("tick").lower() == "x":
            accepted.add(item_id)
            if match.group("star"):
                featured.add(item_id)
    return {"accepted": accepted, "featured": featured, "all": all_ids}
