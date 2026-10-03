"""JSONL-backed stores: the harvested-item corpus, and per-topic decisions.

Generalises soft-currency-observatory's Corpus pattern (observatory/items.py)
rather than insubordinate-terminal's issue-only storage, because it survives
across runs and is incrementally diffable — see CLAUDE.md.
"""
from __future__ import annotations

import json
from pathlib import Path


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            fh.write("\n")
    tmp.replace(path)


class Corpus:
    """All harvested items ever seen, keyed by id. One row per item, latest wins."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._rows = {row["id"]: row for row in _read_jsonl(self.path)}

    def __len__(self):
        return len(self._rows)

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._rows

    def get(self, item_id: str):
        return self._rows.get(item_id)

    def all(self) -> list:
        return list(self._rows.values())

    def upsert(self, item: dict) -> bool:
        """Insert or merge an item. Returns True if this id was new."""
        existing = self._rows.get(item["id"])
        if existing is None:
            self._rows[item["id"]] = item
            return True
        existing["origin"] = sorted(set(existing.get("origin", [])) | set(item.get("origin", [])))
        for field in ("abstract", "pdf_url", "venue", "organisation"):
            if not existing.get(field) and item.get(field):
                existing[field] = item[field]
        existing.setdefault("extra", {}).update(
            {k: v for k, v in item.get("extra", {}).items() if k not in existing.get("extra", {})}
        )
        return False

    def save(self) -> None:
        _write_jsonl(self.path, sorted(self._rows.values(), key=lambda r: r["id"]))


class DecisionStore:
    """Accept/reject decisions for one topic, keyed by item id. Append-only log."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._rows = _read_jsonl(self.path)
        self._latest = {row["id"]: row for row in self._rows}

    def decided_ids(self) -> set:
        return set(self._latest.keys())

    def accepted(self) -> list:
        """Latest decision per id, filtered to accepted. One row per id:
        {id, decision, run, featured, quality, relevance} — quality/
        relevance are the AI scorer's output at review time (None if AI
        scoring didn't run that cycle), carried over from the issue body
        since nothing else persists them (see review.parse_review)."""
        return [row for row in self._latest.values() if row["decision"] == "accepted"]

    def get(self, item_id: str):
        return self._latest.get(item_id)

    def record(self, item_id: str, decision: str, *, run: str, featured: bool = False, quality=None, relevance=None, tags=None) -> None:
        assert decision in ("accepted", "rejected")
        row = {
            "id": item_id, "decision": decision, "run": run, "featured": featured,
            "quality": quality, "relevance": relevance, "tags": list(tags or []),
        }
        self._rows.append(row)
        self._latest[item_id] = row

    def save(self) -> None:
        _write_jsonl(self.path, self._rows)
