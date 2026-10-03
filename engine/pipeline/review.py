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


def _grouped_blocks(items: list) -> list:
    """Items grouped by source_type, each group sorted and rendered to
    markdown blocks: [("## heading (n)", [item_line, item_line, ...]), ...].
    """
    by_type: dict = {}
    for item in items:
        by_type.setdefault(item.get("source_type", "article"), []).append(item)

    blocks = []
    for source_type, heading in SOURCE_TYPE_HEADINGS:
        group = by_type.get(source_type, [])
        if not group:
            continue
        group.sort(key=lambda it: it.get("date") or "", reverse=True)
        group.sort(key=lambda it: it.get("_ai_relevance") or 0, reverse=True)
        blocks.append((f"## {heading} ({len(group)})", [_line(it) for it in group]))
    return blocks


def issue_body(items: list, profile: dict, *, run_label: str) -> str:
    """Render the full review-issue markdown, grouped by source_type, as one
    string. For a candidate list small enough to fit one GitHub issue — see
    issue_bodies() for the general case, which this repo's workflow actually
    uses, since a real run can exceed GitHub's 65,536-char issue body limit.
    """
    lines = [
        f"# {profile.get('title', profile.get('slug'))} — review for {run_label}",
        "",
        f"{len(items)} candidate items. Tick the ones to accept, untick the rest, "
        "then close this issue to publish.",
        "",
    ]
    for heading, item_lines in _grouped_blocks(items):
        lines.append(heading)
        lines.append("")
        lines.extend(item_lines)
        lines.append("")
    return "\n".join(lines)


# GitHub's createIssue GraphQL mutation caps the body at 65,536 characters.
# Leave real headroom: a chunk only decides how many issues get opened, so
# there's no cost to staying well clear of the exact limit.
MAX_ISSUE_BODY_CHARS = 60000


def issue_bodies(items: list, profile: dict, *, run_label: str, max_chars: int = MAX_ISSUE_BODY_CHARS) -> list:
    """Like issue_body(), but splits into multiple issue bodies if the full
    candidate list would exceed GitHub's issue body size limit. Splits only
    at item-line boundaries (never mid-line), so parse_review() works
    unchanged on each resulting issue independently — each closed issue
    just contributes its own items' decisions.

    Returns a list of (title_suffix, body) tuples; title_suffix is ""
    for a single part, else " (part i of n)".
    """
    title = profile.get("title", profile.get("slug"))
    header_line = f"{len(items)} candidate items"
    blocks = _grouped_blocks(items)

    # First pass: does it fit in one issue at all? Render once without a
    # part suffix and check — the common case, and avoids a premature split
    # when the content is close to but under the limit.
    single = issue_body(items, profile, run_label=run_label)
    if len(single) <= max_chars:
        return [("", single)]

    # Doesn't fit: pack items into chunks, never splitting an item line, and
    # re-emitting a section's heading if that section has to continue into
    # the next chunk.
    chunks: list = []  # list of list[str]
    current: list = []
    current_len = 0
    heading_written_in_current = None  # heading string already emitted in `current`, if any

    def _flush():
        nonlocal current, current_len, heading_written_in_current
        if current:
            chunks.append(current)
        current, current_len, heading_written_in_current = [], 0, None

    for heading, item_lines in blocks:
        needs_heading = heading_written_in_current != heading
        for line in item_lines:
            pending = ([heading, ""] if needs_heading else []) + [line]
            added_len = sum(len(l) + 1 for l in pending)
            if current and current_len + added_len > max_chars:
                _flush()
                needs_heading = True
                pending = [heading, "", line]
                added_len = sum(len(l) + 1 for l in pending)
            current.extend(pending)
            current_len += added_len
            heading_written_in_current = heading
            needs_heading = False
        current.append("")
        current_len += 1
    _flush()

    n = len(chunks)
    results = []
    for i, chunk_lines in enumerate(chunks, start=1):
        intro = [
            f"# {title} — review for {run_label} (part {i} of {n})",
            "",
            f"{header_line}, split across {n} issues because of GitHub's issue-size limit "
            f"(this is part {i}). Tick the ones to accept, untick the rest, then close "
            "this issue to publish — each part publishes independently.",
            "",
        ]
        body = "\n".join(intro + chunk_lines)
        results.append((f" (part {i} of {n})", body))
    return results


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
