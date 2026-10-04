"""Load topic profiles and the shared registries. YAML only, never hardcoded
Python — connectors and pipeline code must stay topic-agnostic.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TOPICS_DIR = REPO_ROOT / "topics"
REGISTRY_DIR = REPO_ROOT / "registry"


def load_profile(slug: str) -> dict:
    path = TOPICS_DIR / slug / "profile.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no profile at {path}")
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile.setdefault("slug", slug)
    return profile


def list_topics(*, status: str | None = "active") -> list:
    slugs = []
    if not TOPICS_DIR.exists():
        return slugs
    for child in sorted(TOPICS_DIR.iterdir()):
        profile_path = child / "profile.yaml"
        if not profile_path.exists():
            continue
        profile = load_profile(child.name)
        if status is None or profile.get("status") == status:
            slugs.append(child.name)
    return slugs


def load_registry(name: str) -> dict:
    path = REGISTRY_DIR / f"{name}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def outlets_for_topic(profile: dict) -> list:
    """Resolve a topic's `connectors.rss.outlets` (a list of outlet ids) against
    the shared registry/outlets.yaml, keeping only `status: tested` entries."""
    wanted = set((profile.get("connectors", {}).get("rss", {}) or {}).get("outlets", []))
    registry = load_registry("outlets")
    sources = []
    for outlet in registry.get("outlets", []):
        if outlet["id"] not in wanted:
            continue
        if outlet.get("status") != "tested":
            continue
        sources.append(
            {
                "id": outlet["id"],
                "url": outlet["url"],
                "venue": outlet.get("venue", outlet["id"]),
                "organisation": outlet.get("organisation", ""),
                "source_type": outlet.get("source_type", "news"),
                "connector": "outlet_rss",
                "language": outlet.get("language", "en"),
            }
        )
    return sources


def alert_sources_for_topic(profile: dict) -> list:
    """Resolve a topic's `alerts:` list (Google Alerts feeds Kevin created by
    hand) into RSS source dicts, keeping only `status: tested` entries.

    A feed URL can be given either literally as `feed_url`, or indirectly as
    `feed_url_env: SOME_ENV_VAR` — the latter keeps the URL out of a public
    repo, which matters because a Google Alerts feed URL embeds the Google
    account id that owns the alert and can't be rotated without deleting and
    recreating the alert. An entry naming an env var that isn't set is
    skipped with no source emitted (the caller's health report will simply
    not list it, rather than the run failing).
    """
    from engine.connectors.google_alerts import transform

    sources = []
    for alert in profile.get("alerts", []) or []:
        if not isinstance(alert, dict) or alert.get("status") != "tested":
            continue
        url = alert.get("feed_url") or os.environ.get(alert.get("feed_url_env", ""), "")
        if not url:
            continue
        sources.append(
            {
                "id": alert.get("id", url),
                "url": url,
                "venue": "Google Alert",
                "organisation": "",
                "source_type": alert.get("source_type", "news"),
                "connector": "google_alerts",
                "language": alert.get("language", "en"),
                "transform": transform,
                # A quiet alert legitimately returns nothing — see harvest_rss.
                "empty_ok": True,
            }
        )
    return sources
