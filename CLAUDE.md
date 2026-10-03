# topic-monitor — CLAUDE.md

Generic engine that stands up a literature-and-news monitor for any topic.
One topic (CBDCs) is the pilot; the design must generalize to a second topic
in Phase 2 without writing new scraping code.

Read this file at the start of any session that touches this repo. It is the
persistent memory for the project — architecture, decisions, and why they
were made — so later sessions (Code or Cowork) don't have to rediscover it.

## Ground rules (do not violate)

1. **Never modify** `kevinpdonovan/insubordinate-terminal`,
   `kevinpdonovan/soft-currency-observatory`, or the eNaira Watch repo
   (`kevinpdonovan/enaira-watch`, private, local clone at
   `~/Desktop/Claude Code/enaira-watch`). Read-only references. This repo
   has zero code or package dependency on any of them.
2. **No connector or feed URL goes into `registry/organisations.yaml` or a
   topic's `connectors` list** until a live request against it has returned
   real items in this repo. Untested entries are marked `status: untested`
   and excluded from scheduled runs. This is the single rule the two
   reference repos violated most (see "What we are deliberately not
   repeating" below) — treat it as load-bearing, not advisory.
3. **Secrets never get committed.** GitHub Actions secrets for scheduled
   runs; a local `.env` (gitignored) for interactive sessions.
4. One copy of each shared module (dedupe, scoring, review, build, profile).
   No per-topic forks of pipeline code — topics differ only by
   `topics/<slug>/profile.yaml`.

## Why this repo exists

Kevin runs three monitors today (`insubordinate-terminal`, weekly;
`soft-currency-observatory`, monthly; `enaira-watch`, every 5 days). Each is
a separate repo with its own near-duplicate copy of dedupe/tagger/review/
build/profile code, and each only reliably covers scholarship (via
OpenAlex). Grey literature, books, and official documents are thin or
broken in all three. Standing up a new topic today means forking a repo.
This platform makes a topic a YAML file instead.

## What we're reusing from the two public repos, and why

Full analysis from reading both repos is below; the short version:

- **Item envelope** (id/title/url/doi/source/venue/authors/date/summary/
  origin) — keep, generalize `section`/`kind` into a configurable `channel`.
- **`Corpus` / JSONL persistence pattern** from soft-currency-observatory
  (`observatory/items.py`) — adopt as the canonical store. It's strictly
  more capable than insubordinate-terminal's issue-only storage (survives
  across runs, incremental, diffable).
- **Connector shape**: plain functions returning `(items, health)`, not
  classes. Keep it — it's simple and both repos' connectors are easy to
  read because of it.
- **Dedup**: `item_id` (DOI → cleaned URL → slug title) first, then
  `work_key()` (normalized title + first-author surname) to collapse
  scholarly version-duplicates, then title-Jaccard clustering for syndicated
  news. Keep the approach; **fix the bug** found in production (see below).
- **Two-stage scoring**: cheap keyword/signal gate first, then a Claude API
  batch call (batches of 25, JSON-array-only response) for a 0–3 relevance
  score + tags + one-line reason. Keep the shape; make the AI schema's
  optional fields (themes/places/quality) driven by the topic profile
  instead of hardcoded per repo.
- **Review-by-GitHub-issue**: render a markdown checklist with an
  HTML-comment-encoded id per line (`<!--id:hex10-->`), pre-tick from the
  score, parse the closed issue body back with a regex to get
  accept/reject. This is the best-proven part of both repos — keep as-is.
- **Source health JSON**: `{source, ok, count, note, fail_streak}` per
  connector per run, carried forward across runs. Keep the data model;
  **always** render a dedicated health page (insubordinate-terminal does
  this, soft-currency-observatory buried it in an About page — don't bury
  it here, it's a v1 success criterion).
- **Static site via Jinja2 → GitHub Pages**, built and deployed by the same
  Action that publishes a closed review issue. Keep.
- **YAML topic/org config, never hardcoded in Python**, with a `_lock.yaml`
  file that caches resolved IDs (OpenAlex author/journal/anchor ids) and
  that a human can hand-edit or null out. Keep this pattern for the
  organisation registry and per-topic anchor resolution.

## What we are deliberately not repeating

Confirmed by reading both repos directly (not assumed from the brief):

- **Untested feed URLs reaching production.** insubordinate-terminal's
  `config/sources.yaml` marks ~46 entries `# check` with a docstring
  admitting "couldn't be tested before launch," and its test suite replaces
  the whole file with a synthetic fixture — so those URLs were first
  exercised live, in production, by the scheduled Action. Run
  `2026-W40`'s health.json shows the result: IMF/UNCTAD/CGD/Eurodad/Chatham
  House → 403, BIS/ODI/Finance in Common → 404. **Rule 2 above exists
  specifically to prevent this.**
- **Regex page-watchers as a document source.** `harvest_pagewatch()` is a
  stdlib `HTMLParser` diffing `<a href>` tags against a per-site regex, with
  no JS rendering. Its own failure message says it: "the page may need
  JavaScript or the pattern is wrong." It can only ever say "this page
  changed," never identify a document — which is exactly the eNaira Watch
  failure mode (3 of 2,600 items were official, and all three just flagged
  a CBN listing page as changed, no document identified). Official-document
  connectors in this platform must output `{title, date, pdf_url}` records
  or nothing — never a change flag.
- **A verified dedup gap.** Reproduced directly, not just inferred from the
  brief: `insubordinate-terminal/data/runs/2026-W40/candidates.json`
  contains two records of the same work (Zenodo DOIs `zenodo.22855615` /
  `...616`) that reached the review issue as two separate checkboxes,
  because both records are missing `work_key` entirely — a wiring gap, not
  a Zenodo-specific one. The new pipeline's dedupe stage computes
  `work_key()` unconditionally for every candidate before the merge step
  runs, instead of leaving any code path able to skip it (a regression
  test covers this). Note: an early version of this fix also *asserted*
  that `work_key()` was non-empty for any titled item, which turned out to
  be wrong rather than just extra-safe — it crashed the first live harvest
  run on a Chinese-language title, since the tokenizer is ASCII-only. See
  "Known limitations" below.
- **Five near-duplicate modules with drift.** `dedupe.py` is close to
  line-for-line identical between the two repos (same `STOP` list, same
  functions), differing only in a field name (`section` vs `kind`).
  `tagger.py`, `review.py`, `build.py`, `profile.py` all show the same
  pattern: shared design, forked implementation, silently diverging
  thresholds and schemas. This repo keeps exactly one copy of each,
  parameterized by `topics/<slug>/profile.yaml`.
- **No grey or book channel in the citation-anchored model.**
  soft-currency-observatory can only discover works that cite its anchors
  on OpenAlex/Semantic Scholar — it has no RSS, GDELT, World Bank,
  ReliefWeb, or page-source connector at all, so it structurally cannot see
  anything without a DOI. Anchors/co-citation are useful as one *optional*
  per-topic discovery method here, not the only one.

## Architecture

See the build brief (`docs/build-brief.md`) for the full design — topic
wizard → topic profiles → shared connectors + organisation registry →
pipeline (normalise → dedupe → enrich → score per topic) → review queue per
topic (GitHub issue) → static site (home / topic pages / cross-topic /
source health / digest). Not re-copied here in full to avoid drift between
this file and the brief; CLAUDE.md should only record what changed from the
brief, and why.

## Decisions made (with Kevin, 2026-10-02)

| Decision | Choice | Why |
| --- | --- | --- |
| Repo name / visibility | `kevinpdonovan/topic-monitor`, **public** | Matches the other two reference repos' visibility. |
| Model API | **Claude API** (Anthropic) | `ANTHROPIC_API_KEY` as a GitHub Actions secret. Haiku for bulk per-item scoring (cheap, matches both reference repos' `TAGGER_MODEL` convention), a stronger model for the wizard's term-expansion step. |
| Paid search API (Exa/Brave) | **Skipped for v1** | Launch on free connectors only (OpenAlex, World Bank, ReliefWeb, sitemaps, Google Alerts RSS). Revisit once source-health data shows how much grey-lit coverage is actually missing without it — don't pay for it speculatively. |
| Pilot topic / cadence | **CBDCs, monthly** | CBDCs stays the pilot through all phases per the brief; cadence set to monthly rather than weekly to keep the review load light while the engine is still being built. |
| Existing Google Alerts | **None to import** | Wizard starts clean; no dedupe-against-existing-alerts step needed. |

## Open questions (not blocking Phase 0/1, revisit before Phase 2)

- Which publishers to watch for books (needed before the publisher-feed
  connector in Phase 2).
- Whether Edinburgh library provides Overton / Policy Commons / WorldCat
  access (Phase 3, optional).
- Whether a self-hosted runner is needed for institutional sites that block
  GitHub Actions' datacentre IPs (decide once Phase 2's organisation
  registry testing shows which sites actually block it — don't pre-solve).
- Project inbox setup for the email-alert harvester, if we want that
  connector (both reference repos have one via IMAP app-password; not
  committed to using it here yet).

## Infrastructure

Python 3.12. State is files in-repo for v1 (JSONL for items/decisions, YAML
for config) — move to SQLite only if that becomes unwieldy. GitHub Actions
for scheduled runs, GitHub Pages for the site, matching both reference
repos' proven deploy pattern (`actions/configure-pages` →
`actions/upload-pages-artifact` → `actions/deploy-pages`).

```
topic-monitor/
  CLAUDE.md
  docs/build-brief.md           the original design brief, unmodified
  registry/organisations.yaml   shared institution registry
  registry/outlets.yaml         news outlet allowlist
  topics/<slug>/profile.yaml    one folder per topic
  topics/<slug>/alerts.md       wizard's Google Alerts checklist
  engine/connectors/            one module per connector
  engine/pipeline/              normalise, dedupe, enrich, score, review
  engine/wizard/                new-topic command
  site/                         templates and static assets
  data/items.jsonl              all harvested items
  data/decisions/<slug>.jsonl   accept/reject per topic
  data/health/                  per-run health reports
  tests/                        unit tests + recorded connector fixtures
  .github/workflows/            harvest, review, publish
```

## Status

Phase 0 done. Phase 1 (engine with scholarship and news) written, and as
of the second live run on 2026-10-03 confirmed end-to-end on real data:
OpenAlex, GDELT and all 6 RSS outlets harvest correctly, dedupe no longer
crashes, and the review-issue split fix is in place for when the
candidate list is large. The one thing still not live-verified is AI
scoring, blocked on Kevin fixing the API key's workspace scoping (see
below) — the pipeline doesn't depend on it to function, just to produce
relevance scores/pre-ticks. Specifics:

**Built:** item schema (`engine/pipeline/items.py`), JSONL corpus +
decisions store (`corpus.py`), connectors for OpenAlex / GDELT / generic
RSS (`engine/connectors/`), dedupe with the work_key fix
(`dedupe.py`), two-stage scoring — keyword gate always, Claude API batch
call if `ANTHROPIC_API_KEY` is set (`score.py`), review-issue
render/parse (`review.py`), health aggregation (`health.py`), Jinja2 site
build (`build.py`), CLI (`harvest` / `publish` / `build`), the three
GitHub Actions workflows, 17 unit tests (6 using fixtures recorded live on
2026-10-02), the CBDC topic profile, and `registry/outlets.yaml` with 6
live-tested outlets (7 more confirmed dead and kept on record, not
deleted).

**Verified locally with real data** (this sandbox only has Python 3.7, so
`feedparser`/`anthropic` can't install — see below): ran the full harvest →
dedupe → keyword-gate → review-issue-render → parse → decisions → corpus →
health → site-build loop against live OpenAlex results for all 5 CBDC
queries. 500 raw items → 396 after dedupe (104 exact+version duplicates
collapsed, 0 residual duplicate groups in the final candidate set) → 232
keyword-gate survivors (213 articles, 17 chapters, 1 report, 1 book). All
three Phase 1 success criteria met on this slice:
  - [x] CBDC topic produces a review issue with ≥30 relevant items (232 ≫ 30)
  - [x] Duplicate rate in the review issue <5% (0% residual, confirmed by
        re-running work_key clustering over the final candidate list)
  - [ ] Every enabled source shows `ok` or a reasoned `broken` — true for
        OpenAlex and the 6 RSS outlets (tested live via curl), **not yet
        confirmed for GDELT** (see below) or AI scoring (no key set yet)
This demo run's output was reset before committing — it used the
pre-tick defaults as a stand-in for Kevin's real review, which isn't a
real decision and shouldn't sit in the corpus as if it were one. The
actual first run should happen for real via the harvest workflow once
this is pushed, producing a real GitHub issue for Kevin to review by hand.

**First live run on GitHub Actions (2026-10-03): failed, root-caused, fixed.**
Kevin added `ANTHROPIC_API_KEY` and `CONTACT_EMAIL` as repo secrets/vars
and ran the `Harvest` workflow by hand. It failed after 51s on real
harvested data (not a config problem): `merge_versions()`'s defensive
`assert wk or not item.get("title")` — added to guard against the Zenodo
wiring gap above — fired on an item whose title is entirely
non-Latin-script, where `title_tokens()`'s ASCII-only regex legitimately
produces zero tokens. The assert was wrong, not just strict: the existing
`if not wk: singles.append(item)` fallback already handled this case
correctly, but never got to run. Fixed by removing the assert (see
`dedupe.py` and "Known limitations" below); added a regression test
(`test_merge_versions_does_not_crash_on_a_non_latin_title`). Separately,
the first push's `Build and deploy site` run also failed — GitHub Pages
wasn't enabled yet for this repo. Fixed directly in repo Settings → Pages
→ Source: GitHub Actions (one-time setup, not a review decision, so done
without asking).

**Second live run (2026-10-03, same day, after the dedupe fix): harvest
itself succeeded — OpenAlex, GDELT and all 6 RSS outlets all ran and
reported honest health — but issue creation failed on a second real bug:**
`data/health/2026-10-03.json` and `topics/cbdc/review/2026-10-03.md` (both
committed by the run before it failed, so this is real production data,
not a guess):
  - **951 raw items** harvested (OpenAlex 150×5 queries — capped by
    `max_pages=3`, not a real ceiling; 6/6 RSS outlets ok, counts matching
    the registry notes exactly, including ledgerinsights' known 1-item
    cap), → **322 keyword-gate candidates**, comfortably clearing the
    ≥30-item criterion with real multi-connector data, not just OpenAlex.
  - **GDELT: confirmed 429-rate-limited from the GitHub Actions runner's
    IP too**, not just this build sandbox — both queries failed the same
    way. Not a bug (the connector is supposed to report this honestly
    rather than retry-loop into a longer outage), just a confirmed, real
    constraint on this source.
  - **AI scoring failed**: `Error code: 400 ... "This API key is not
    scoped to a workspace ... Add the header, or use an API key that is
    scoped to a workspace."` — the `ANTHROPIC_API_KEY` Kevin added is an
    org-level key, not a workspace-scoped one. This needs Kevin to fix in
    the Anthropic Console (Settings → API Keys → create a key scoped to a
    specific workspace) and update the GitHub secret — not something to
    route around in code. Scoring still ran in keyword-gate-only mode
    (that stage doesn't need AI), so this blocked relevance scores/tags/
    featured-starring, not the harvest itself.
  - **The real bug**: `topics/cbdc/review/2026-10-03.md` is 86,602
    characters — over GitHub's 65,536-char issue-body limit, so
    `gh issue create` failed with `Body is too long`. My local smoke test
    (Status, above) only used OpenAlex and landed at 60KB; add GDELT/RSS
    and it crossed the real limit. Fixed by splitting the render into
    multiple issues when needed: `review.issue_bodies()` packs items into
    ≤60,000-char chunks at item-line boundaries (never mid-line), each a
    self-contained issue body with its own "(part i of n)" header: `cli.py`
    now writes one review `.md` file per chunk, and `harvest.yml`'s
    existing per-file issue-creation loop picks all of them up unchanged —
    each part is reviewed and closed independently, and `publish.yml`
    needs no changes since it already only looks at the one issue that
    closed. Added a regression test built from this real 322-item/86KB
    case shape (`test_issue_bodies_splits_when_over_the_limit_regression`).

## Known limitations

- `dedupe.py`'s `work_key()` can't version-merge items whose title is
  entirely non-Latin-script (Chinese, Japanese, Arabic, Cyrillic, ...) —
  `title_tokens()` uses an ASCII-only regex. Such items just don't get
  version-deduped (not a crash, not data loss — see `merge_versions()`),
  which matters for this topic specifically: e-CNY/digital-yuan coverage
  is exactly the kind of source likely to have Chinese-language titles.
  Worth revisiting if the health/duplicate-rate data after a few runs
  shows this losing real duplicates.

**Not done, and intentionally deferred (see "What we're reusing" above):**
  - Real embedding-similarity as scoring stage 1, per the build brief's
    pipeline design — using the reference repos' proven keyword/term-gate
    instead, since embeddings would mean picking and paying for a new
    provider (Claude has none) that wasn't part of the API decision Kevin
    already made. Revisit once there's enough accept/reject history to
    tell whether the keyword gate's false-negative rate actually matters.
  - The `new-topic` wizard, organisation registry, grey-lit/book
    connectors, official-document scrapers — all Phase 2.

## Next steps before Phase 1 is fully closed out

1. ~~Push Phase 1 commit~~ — done (`aac9e03`, via GitHub Desktop — no
   stored git credential on this machine, so every push needs that step).
2. ~~Add `ANTHROPIC_API_KEY` and `CONTACT_EMAIL`~~ — done by Kevin.
3. ~~Run `Harvest` by hand (1st try)~~ — failed on the dedupe crash. Fixed,
   pushed (`8770479`), confirmed GitHub Pages also needed enabling in repo
   Settings (done).
4. ~~Re-run `Harvest` (2nd try)~~ — harvest itself succeeded (OpenAlex,
   GDELT, all 6 RSS outlets, real health data, 322 candidates); failed at
   issue-creation on the 65,536-char body limit. Fixed via `issue_bodies()`
   chunking (this commit).
5. Push this commit (same GitHub Desktop step).
6. Re-run `Harvest` a third time — this time should open a real review
   issue (or several, if still over the per-issue limit) on GitHub.
7. Kevin: fix the Anthropic API key's workspace scoping (Console →
   Settings → API Keys → create/use a key scoped to a specific workspace)
   and update the `ANTHROPIC_API_KEY` secret, whenever convenient — not
   blocking the review issue, only blocks AI relevance scores/pre-ticks.
8. Kevin reviews and closes the review issue(s).
9. Confirm `Publish review` fired (Actions tab → green check, and
   `data/decisions/cbdc.jsonl` has a new commit) and `Build and deploy
   site` fired after it — then open the live Pages URL (Settings → Pages,
   or the `deploy` job's output in that workflow run) and check the CBDC
   topic page shows the accepted items and the health page shows real
   source status.
