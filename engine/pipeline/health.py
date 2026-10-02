"""Per-connector/per-source health: what returned items, what failed, and
for how many runs in a row. Same JSON contract both reference repos use.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def aggregate_health(results: list, *, previous: dict | None, run_label: str) -> dict:
    """`results` is a flat list of {source, ok, count, note} rows from every
    connector call this run. `previous` is the last health.json written (or
    None). Returns the new health.json content, carrying fail_streak forward.
    """
    prev_by_source = {row["source"]: row for row in (previous or {}).get("sources", [])}
    sources = []
    for row in results:
        prev = prev_by_source.get(row["source"])
        streak = prev.get("fail_streak", 0) if prev else 0
        streak = 0 if row["ok"] else streak + 1
        sources.append({**row, "fail_streak": streak})

    ok_count = sum(1 for s in sources if s["ok"])
    return {
        "run": run_label,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "stats": {
            "sources_total": len(sources),
            "sources_ok": ok_count,
            "sources_failing": len(sources) - ok_count,
            "items_total": sum(s["count"] for s in sources),
        },
    }


def load_health(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_health(path: Path, health: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(health, indent=2, sort_keys=True), encoding="utf-8")


def repeated_failures(health: dict, *, min_streak: int = 3) -> list:
    """Sources that have failed `min_streak` runs in a row — candidates for
    an auto-opened issue."""
    return [s for s in health.get("sources", []) if s["fail_streak"] >= min_streak]
