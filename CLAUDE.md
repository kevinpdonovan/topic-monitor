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

**2026-10-03, after seeing the first real review issues:**

| Decision | Choice | Why |
| --- | --- | --- |
| Site search | **Client-side, JSON-index-driven** (`site/static/topic.js` + per-topic `items.json`) | Kevin has said before that a non-searchable interface isn't usable for him ([[kevin-prefers-built-not-instructed]] in memory). Matches the build brief's "client-side full-text search" Presentation requirement, which Phase 1 had skipped. No server needed — fits the static-site design. |
| Monthly view | **Client-side toggle on the same page**, not separate pre-rendered monthly pages | Kevin wants to view publications by month as well as the full archive. A JS toggle (grouping the same `items.json` by `date`'s year-month) does both without doubling the number of generated pages or losing search/filter state when switching views. |
| Quality tiers (high/medium/low) | **AI-judged per item, NOT from journal prestige/h-index/citations** | Kevin was explicit: favor empirical work with real evidence (esp. case studies) and strong theoretical/conceptual contributions; hold "systematic reviews"/"literature reviews" to a high bar by default; and actively value heterodox, anti-systemic and Global South political economy work rather than penalizing it for being unfamiliar or non-mainstream. Implemented as a rubric in `score.py`'s AI prompt, with `registry/quality_signals.yaml` supplying a list of known-rigorous heterodox/Global South sources as positive context — deliberately asymmetric (no equivalent "mainstream prestige" list), since adding one would just reproduce the Eurocentric bias this exists to counter. |
| Historical backfill | **One-time, manually-triggered, scholarship-only, age-weighted citation pre-filter, start at 1 year back** | Kevin wants to pull further back than the regular 12-month window, winnowed so an old uncited piece doesn't make the cut but a recent one isn't held to the same citation bar (it hasn't had time to accumulate any). `engine/pipeline/backfill.py`'s `min_citations_for_age()` gives a grace period (default 90 days, always passes regardless of citations) then requires linearly more citations per month beyond it — explicitly a volume-reduction step before the same AI quality rubric runs, not a quality judgment itself (a flat citation cutoff would reproduce exactly the recency bias the quality-tier design above was built to avoid). GDELT/RSS have no multi-year history via their feeds, so this is OpenAlex-only. Started at 1 year back per Kevin's instruction, not the 5 he first floated — `--years-back` is a CLI/workflow parameter, trivial to push further once the 1-year run's output has been sanity-checked. |
| Post-hoc corrections from the site | **Instant browser-local effect, plus an explicit "send corrections" hand-off that makes it real** | Kevin wants to cull junk while *reading* the site, not only during review — things slip through and you only notice later. A static page can't write to the repo, and a token in client-side JS is out of the question, so hiding/muting is `localStorage` for immediate effect, with a button that exports the marks as a `corrections` issue for a session to apply to the decisions store. The page states plainly that marks are browser-local until sent, rather than implying a decision stuck. Muting a source also needed real teeth: `excluded_venues:` in the topic profile, enforced in `keyword_gate` — venues mostly come from OpenAlex, so `registry/outlets.yaml` couldn't express it. |
| Google Alerts feed URLs | **Read from env/Actions secrets (`feed_url_env`), never committed** | Kevin created the first alert by hand on 2026-10-04 and the feed URL embeds his Google account id. This repo is public and git history is permanent, so the URL is referenced indirectly by variable name from `topics/<slug>/profile.yaml`. Confirmed with Kevin rather than assumed — the build brief's own schema says to store the RSS URLs in the profile, which predates the repo being public. Each new alert needs its secret added in repo Settings and one passthrough line in `harvest.yml`. |
| New-topic wizard entry point | **Site form → pre-filled GitHub issue → a live Claude Code session works it from there, asynchronously** | Kevin wants to search/request a new topic from the site and have Claude ask clarifying questions. A static GitHub Pages site has no backend, and putting an Anthropic API key in client-side JS to enable live chat would be a real security/cost problem — confirmed with Kevin this async, issue-mediated hand-off (matching how review issues already work, and matching the build brief's own wizard design, which explicitly runs "inside a Claude Code session so a model is available") is the right shape, not instant in-page chat. See "Handling a new-topic request" below. |

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

Phase 0 done. Phase 1 (engine with scholarship and news) written and, as
of the fourth live run on 2026-10-03, confirmed end-to-end on real data:
OpenAlex, GDELT and all 6 RSS outlets harvest correctly, dedupe no longer
crashes, and the review-issue split produced two real, correctly-sized,
correctly-labeled GitHub issues (#1, #2 — 296+26 research/report/book
items between them) that Kevin can review right now. AI scoring still
isn't live-confirmed — the workspace-scoping error is fixed, but a second,
different bug (empty `TAGGER_MODEL` env var, see below) blocked it on this
same run; the fix is written, needs one more run to confirm. Specifics:

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

**Third live run (2026-10-03, after the chunking fix, and after Kevin
fixed the API key's workspace scoping): two real bugs, both found from the
actual run output, not guessed.**
  1. **Issue creation still failed** — but this time it was stale data, not
     a sizing bug: `gh issue create` succeeded for the two new, correctly-
     sized chunks (opened issues #1 and #2 — real, valid, still open for
     Kevin to review), then failed with the *same* "Body is too long" error
     on `topics/cbdc/review/2026-10-03.md`, an 86,602-char leftover from
     the *first* failed run that harvest.yml's `topics/*/review/*.md` glob
     picked up again because nothing had ever deleted it. These review
     files exist only to hand content to `gh issue create` — nothing
     re-reads them once an issue exists — so `cmd_harvest` now clears a
     topic's `review/` directory before writing each run's files (`cli.py`).
     Removed the stale file from the repo directly.
  2. **AI scoring: workspace-scoping error gone, replaced by a different
     one** — `Error code: 400 ... "model: String should have at least 1
     character"`. Cause: `harvest.yml` always sets the `TAGGER_MODEL` env
     var to `${{ vars.TAGGER_MODEL }}`, and GitHub Actions renders an
     unset repo variable as an *empty string*, not an absent env var — so
     `os.environ.get("TAGGER_MODEL", "claude-haiku-4-5")` returned `""`
     instead of falling back, since `.get`'s default only applies to a
     *missing* key, not an empty value. Kevin had correctly left the
     variable unset per my own earlier instructions; this was my bug, not
     a setup mistake. Fixed with `os.environ.get("TAGGER_MODEL") or
     "claude-haiku-4-5"` (`cli.py`) — still needs a live run to confirm AI
     scoring actually completes now, not just that this particular error
     is gone.

**What's confirmed solid after three real runs:** harvest (OpenAlex/GDELT/
RSS), dedupe, keyword-gate scoring, issue splitting, and issue creation
with real, correctly-formatted, interactive checkboxes (verified by
opening issue #1 in the browser — pretick state, `matched [...]` reasons,
and the "(part 1 of 2)" framing all rendered correctly). Two real open
issues exist right now for Kevin to review:
[#1](https://github.com/kevinpdonovan/topic-monitor/issues/1) (296
articles + some books/reports) and
[#2](https://github.com/kevinpdonovan/topic-monitor/issues/2) (26 items) —
part of the same 322-candidate run. Not re-harvesting again before those
are reviewed, to avoid opening redundant duplicate issues for the same
undecided items.

**Kevin closed both issues (2026-10-03): a fourth real bug, found by
actually checking rather than assuming the chain worked.** `Publish
review` ran and succeeded for both (`data/decisions/cbdc.jsonl` has the
real 219-accepted/103-rejected result), but `Build and deploy site` never
ran again after the very first manual push — checked the Actions tab
directly rather than taking the green "Publish review" checks as proof
the site was live. **Root cause: a push made with the default
`GITHUB_TOKEN` (as every commit `harvest.yml`/`publish.yml` make) does not
trigger other workflows' `on: push` — GitHub's anti-recursion
protection.** `pages.yml` was only ever reachable by a human-authored push
or manual dispatch, so every harvest/publish commit silently failed to
rebuild the live site. Fixed by adding `workflow_call` to `pages.yml` and
having `publish.yml` call it directly (`uses: ./.github/workflows/
pages.yml`) right after committing decisions, instead of relying on the
push trigger at all. Rebuilt the site locally with Kevin's real 219
accepted items to confirm the new site (search/quality-filter/monthly-view
included — see the decisions table above) renders correctly against real
data before pushing; not yet confirmed via the actual workflow run.

**Also added, same session, before pushing:** quality tiers
(high/medium/low, AI-judged per the rubric in `score.py`, fed by
`registry/quality_signals.yaml`), a monthly view toggle, and client-side
search — see the decisions table above for why each exists. These extend
the review-issue comment encoding (now `<!--id:...;quality:...;
relevance:...;tags:...-->`) and `DecisionStore.record()` (now also stores
quality/relevance/tags) so quality survives from the AI scorer through the
issue, into the decision record, onto the site. Both of Kevin's real
closed issues predate this — their 219 accepted items show as "Unscored"
on the site, which is correct (they really weren't AI-scored, since that
run hit the TAGGER_MODEL bug), not a bug in the new code.

**Fifth live run (2026-10-03, confirming the above): a fifth real bug,
caused directly by re-running `Harvest` for testing rather than waiting
for the next real cycle.** This run found almost no new candidates
(OpenAlex itself got 429-rate-limited this time, from re-running harvest
four times today against the same IP — not a bug, just a side effect of
testing cadence) and recorded `ai_score: ok=true, count=0` — the
workspace-scoping and TAGGER_MODEL bugs are both confirmed actually fixed
now, there was just nothing new to score. But because `candidates` came
back empty, the first-pass fix above (clear old review files before
writing new ones) never ran — it was gated behind the same `if not
candidates` check it needed to run ahead of. The stale, already-published
`part1.md`/`part2.md` from the prior run were still sitting in
`topics/cbdc/review/`, and `harvest.yml`'s blind `*.md` glob re-opened
them as issues **#3 and #4 — duplicates of the already-closed, already-
published #1 and #2.** Caught by checking the Issues tab directly rather
than assuming "Harvest succeeded" meant everything downstream was fine;
closed both as duplicates (with a comment explaining why) before they
could confuse Kevin or get acted on. Fixed properly this time: the
review-directory clear now happens unconditionally, before the
candidates check, not after it (`cli.py`) — the right fix is "always
clear, then decide whether to write," not "clear only when writing."

## Known limitations

- **Unreviewed self-deposits were being rated high** (found 2026-10-05,
  **addressed the same day** — kept here because the reasoning matters if
  anyone is tempted to revisit the rubric). While checking whether the
  anti-prestige instruction was doing real work — it is: 10 of 35 high
  ratings went to venues with no prestige signal at all — the same
  openness turned out to cut the other way. One author had six
  self-published Zenodo deposits in a single review (a numbered
  "Sovereign Digital Infrastructure Series"), four rated high. The scorer
  sees a technically detailed abstract and credits it, with no
  peer-review signal available to temper the judgment. Another Zenodo
  record listed its authors as "Daniel Rosehill, Gemini 3.1 (Flash),
  Chatterbox TTS" — AI models as co-authors.
  Kevin's call was to add one sentence to the rubric rather than change
  anything structural: an unreviewed self-deposit now needs stronger
  evidence to reach "high", while a research-institute working paper or
  well-evidenced preprint can still get there on substance. The sentence
  says explicitly that this is about *whether the work has been checked
  by anyone*, not the venue's status, and that it does not license
  downrating unfamiliar or non-Anglophone venues — otherwise it would
  quietly undo the heterodox instruction immediately above it. Watch the
  next scored run: if high ratings for regional journals and Global South
  institutions drop, the carve-out is leaking and should be narrowed.

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
  - The organisation registry, grey-lit/book connectors, official-document
    scrapers — still Phase 2. The new-topic wizard's entry point and
    expansion tooling are built now (see "Handling a new-topic request"
    below), ahead of schedule, at Kevin's request — the rest of Phase 2
    is unaffected.

## Applying corrections from the site

Each topic page has per-item `bookmark` / `hide` / `mark low` /
`mute source` controls, a source list with mute toggles, and a
"★ Bookmarked (N)" view that filters to bookmarks only — which composes
with the existing All time / By month toggle, so bookmarks can be read
either way without a separate page. The bookmarked view deliberately
ignores the quality filter and suppression: a bookmark is an explicit
"keep this", and having one vanish because a quality checkbox was
unticked elsewhere would be baffling. **Those marks are browser-local
only** —
they're stored in `localStorage` under `topic-monitor:<slug>`, so they
take effect instantly and survive reloads, but they live in one browser,
teach the pipeline nothing, and vanish if site data is cleared. The page
says so, in those words, rather than implying the decision stuck.

The **"Send corrections →"** button turns them into a pre-filled GitHub
issue labeled `corrections`, listing item ids + titles and muted source
names. When one of those arrives, apply it properly:

- **Bookmarked — feature these** → set `featured: true` on that id's
  decision record. Bookmarks aren't corrections (they're Kevin's reading
  list) but they ride along in the same export so they aren't stranded in
  one browser; `featured` is the existing field that already renders a
  badge site-wide, so it's the natural home rather than a parallel
  mechanism.
- **Reject these items** → record each id as `rejected` in
  `data/decisions/<slug>.jsonl` (`DecisionStore.record`). This both drops
  them from the site and stops them ever being offered again, since
  `cmd_harvest` filters candidates against `decided_ids()`.
- **Mark these low quality** → set `quality: "low"` on that id's decision
  record. It stays accepted and on the site, but falls under the Low
  filter so Kevin can bulk-hide it.
- **Stop harvesting these sources** → add the venue to the topic
  profile's `excluded_venues:`. Note this is *not* usually a
  `registry/outlets.yaml` change: the site's source list shows item
  venues, and most of them (Zenodo, SSRN, a journal name) arrive via
  OpenAlex rather than being configured RSS outlets. `outlets.yaml` is
  only right when the muted source genuinely is one of the configured
  feeds. `keyword_gate` enforces `excluded_venues` with an exact,
  case-insensitive match, so "Zenodo" won't swallow "Zenodo Review of
  Economics".

Then rebuild (`python -m engine build`) so the site reflects it, and
tell Kevin he can clear his local marks for anything now applied upstream
(they're harmless if left — the item is gone from `items.json` anyway).

## Handling a new-topic request

The site's homepage has a "Request a new topic" form
(`site/templates/index.html` + `site/static/new-topic.js`) that opens a
pre-filled GitHub issue, labeled `new-topic`, under Kevin's own account —
nothing on the page talks to a model. **Nothing automated processes that
issue.** A live Claude Code session has to pick it up — when you see one
open:

1. Read the seed terms and notes in the issue body.
2. Run `CONTACT_EMAIL=<email> python -m engine wizard-expand --seed <term1> <term2> ...`
   to sample OpenAlex and see what related concepts/keywords come up
   ranked by relevance score. This is a research aid, not a
   decision-maker — read the candidates yourself and use judgment.
   Confirmed live, 2026-10-03, seeding "mould" + "housing UK": a
   polysemous seed term pulls in multiple unrelated senses (that one got
   metal-casting, cheese-making and mycology alongside the intended
   damp-housing-conditions sense) — raw co-occurrence frequency alone is
   noisy (OpenAlex tags broad discipline-level concepts like "Economics"/
   "Biology" onto nearly everything); `wizard-expand` already filters to
   specific-enough concepts and ranks by relevance score, but the
   remaining ambiguity between genuinely different senses/angles is
   exactly what step 3 is for.
3. Comment on the issue with a shortlist of proposed keywords — grouped
   by the different senses or angles you're seeing, if the seed term
   turned out ambiguous — and 1–3 clarifying questions (which angles,
   which disciplines, which places/languages matter, anything to
   exclude). Don't guess past real ambiguity; ask, the way the brief
   itself expects ("do you want this aspect?", "these disciplinary
   perspectives?").
4. Once Kevin replies, iterate if needed, then write
   `topics/<slug>/profile.yaml` (same shape as `topics/cbdc/profile.yaml`)
   and `topics/<slug>/alerts.md` — the Google Alerts checklist per the
   build brief's "Alerts (semi-automated)" step: query strings for Kevin
   (or Claude in Chrome acting in his account) to paste into Google
   Alerts by hand, pasting the resulting feed URLs back. **Never** try to
   script Google Alerts creation itself — it has no API, and the brief is
   explicit that nothing should drive a logged-in browser to fake one.
5. Open a PR adding the new topic folder. Don't harvest for it until
   Kevin merges — the PR is the approval gate, same principle as every
   other topic-folder change.
6. Close the `new-topic` issue once the PR is open (or merged — either is
   fine, just don't leave it open indefinitely once the real work has
   moved to the PR).

This is deliberately not automated end-to-end. Per the build brief's own
design, the wizard "runs inside a Claude Code session so a model is
available" — the judgment calls here (which terms actually matter, what
Kevin means by an ambiguous seed term) need a live conversation, not a
script making assumptions.

## Next steps before Phase 1 is fully closed out

1. ~~Push Phase 1 commit~~ — done (`aac9e03`).
2. ~~Add `ANTHROPIC_API_KEY` and `CONTACT_EMAIL`~~ — done by Kevin.
3. ~~Run `Harvest` (1st try)~~ — failed on the dedupe crash. Fixed, pushed
   (`8770479`); also enabled GitHub Pages in repo Settings (was disabled).
4. ~~Re-run `Harvest` (2nd try)~~ — harvest succeeded; failed at
   issue-creation on the 65,536-char body limit. Fixed via `issue_bodies()`
   chunking, pushed (`b1d2529`).
5. ~~Kevin fixed the API key's workspace scoping~~ — done.
6. ~~Re-run `Harvest` (3rd try)~~ — opened two real review issues (#1, #2);
   also hit the stale-file bug and the empty-`TAGGER_MODEL` bug, both
   above. Both fixed, not yet pushed.
7. ~~Push~~ — done (`4ba7d0f`).
8. ~~Kevin reviews and closes issues #1 and #2~~ — done, 2026-10-03: 219
   accepted, 103 rejected. `Publish review` succeeded for both (checked
   the Actions tab directly, not assumed).
9. ~~Confirm `Build and deploy site` fired after `Publish review`~~ — it
   didn't: found the `GITHUB_TOKEN`-push-doesn't-trigger-workflows bug
   (above). Fixed (`publish.yml` now calls `pages.yml` directly via
   `workflow_call`); not yet confirmed via an actual workflow run, only by
   rebuilding the site locally against Kevin's real 219 accepted items.
10. ~~Added quality tiers, monthly view, client-side search~~ — done,
    pushed (`196ee90`). Confirmed `Build and deploy site` actually fires
    now too (`workflow_call` fix) and the live Pages URL serves the real
    site with Kevin's 219 accepted items — search, quality filter, and
    the all-time/by-month toggle all work.
11. ~~Re-run `Harvest` to confirm AI scoring end-to-end~~ — ran (#4):
    confirmed `ai_score` no longer errors (both earlier bugs are really
    fixed), but found a fifth real bug: the review-directory-clear fix
    only ran when there were new candidates, so a near-empty run (almost
    everything already decided, OpenAlex itself rate-limited from
    re-running harvest four times today) left stale already-published
    files in place, and they got re-opened as duplicate issues (#3, #4).
    Closed both as duplicates of #1/#2 with an explanation. Fixed
    properly: the clear is now unconditional. Not yet pushed.
12. ~~Push this commit~~ — done (`cd5f39b`).
13. ~~Confirm AI scoring produces real relevance/quality scores~~ — **done,
    2026-10-05, Harvest #5**: `ai_score ok=true, count=157`. Quality came
    out 35 high / 83 medium / 39 low; relevance 65 at 3, 78 at 2, 13 at 1,
    1 at 0. Literature reviews were held to the intended high bar (6 of
    them: 1 high, 4 medium, 1 low). A venue cross-tab confirmed the rubric
    is not simply tracking prestige — 10 of 35 high ratings went to bare
    repository/preprint deposits (Zenodo, arXiv, SSRN, a Harvard Dataverse
    replication dataset) and several to Lithuanian, Serbian, Venezuelan
    and Spanish-language journals; only 2 of 35 were New Political
    Economy. Same run also confirmed, all previously untested live: the
    Google Alerts source resolving from its secret, `empty_ok` reporting a
    quiet alert as healthy rather than failing, OpenAlex recovered from
    the rate limit, and no duplicate issues (the unconditional review-dir
    clear holds). GDELT 429'd for the fourth consecutive run, which now
    looks permanent from Actions IPs rather than transient.
14. Added `backfill.yml` + `python -m engine backfill` (same session): a
    one-time, manually-triggered, OpenAlex-only historical pull with the
    age-weighted citation pre-filter (see decisions table above). Not yet
    run for real — next step is pushing this and triggering it by hand
    (`--topic cbdc --years-back 1`, GitHub's default inputs match that)
    once OpenAlex's rate limit from today's repeated testing has cleared,
    same caution as #13.
15. Added the new-topic wizard's entry point (site form → pre-filled
    GitHub issue) and `wizard-expand` tooling (same session) — see
    "Handling a new-topic request" above. Created the `new-topic` label
    directly in repo Settings (one-time setup, same as `review`/
    `topic:*`). Verified live: the form builds a correct pre-filled issue
    URL (checked via the actual GitHub "Create new issue" page — title,
    body, and label all populated correctly) and `wizard-expand` found
    genuinely useful, well-ranked candidate terms on a real run (seeded
    "mould" + "housing UK"). Not yet pushed. No `new-topic` issue has
    been worked end-to-end yet — next real request is the first live
    test of steps 3–6 above.
16. Push this commit.
