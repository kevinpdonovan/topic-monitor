# topic-monitor

One generic engine for standing up a literature-and-news monitor for any
topic. Topics are configuration (`topics/<slug>/profile.yaml`); connectors
and the pipeline are shared and topic-agnostic.

Pilot topic: CBDCs, monthly cadence.

See [CLAUDE.md](CLAUDE.md) for architecture and decisions, and
[docs/build-brief.md](docs/build-brief.md) for the original design brief.

Status: Phase 0 done. Phase 1 engine (OpenAlex, GDELT, RSS, dedupe,
two-stage scoring, review-by-issue, basic site, source health) written
and locally verified against live data where this sandbox allows — see
CLAUDE.md for exactly what's confirmed vs. still needs a real GitHub
Actions run.
