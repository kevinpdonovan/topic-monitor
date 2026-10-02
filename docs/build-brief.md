# Topic Monitor Platform — Build Brief for Claude Code

Oct 2, 2026 · @Kevin Donovan

## Goal

Build one generic engine that stands up a new literature-and-news monitor for any topic in under an hour of human time. Today the topic is CBDCs; next week it may be stablecoins, Sri Lanka's economy or Safaricom. Each topic runs in parallel on shared infrastructure and gets its own page, review queue and digest.

The platform must cover what the existing tools miss: grey literature (NGOs, think tanks, IFIs, central banks, financial institutions), books, and official primary documents. Scholarship and news stay in, but they are the easy part.

Success criteria for version 1:

- A new topic goes from seed keywords to a first populated page in one session, with fewer than 15 minutes of clicking (mostly creating Google Alerts).
- Every result carries a source type: article, book, chapter, working paper, report, policy or official document, news, discourse, podcast.
- Grey literature and books make up a visible share of each topic's accepted items, not a token handful. Target: at least 20% of accepted items are non-journal after the first month.
- A source health page shows, per connector and per topic, what returned items, what failed and why.
- The design stays open to other users later, but v1 is single-user (Kevin).

## Ground rules for Claude Code

1. **Do not modify the existing products.** Never edit, commit to, or open pull requests on `kevinpdonovan/insubordinate-terminal`, `kevinpdonovan/soft-currency-observatory`, or the eNaira Watch repo. Read them only. The new platform lives in a new repo.
2. **Learn from them, don't copy them blindly.** Reuse ideas and code patterns where they worked (OpenAlex harvesting, citation trails, GitHub-issue review, source health). Rewrite rather than import, so the new engine has no dependency on the old repos.
3. **Ask for what you can't see.** If a design question depends on something in Kevin's other Claude Code or Cowork sessions, his local files, private repos or accounts, stop and ask him for it rather than guessing. Known gaps are listed in the last section.
4. **Test every source before relying on it.** No connector or feed URL goes into the default registry until a live request has returned real items. Untested entries are marked `status: untested` and excluded from runs.
5. **Keep secrets out of the repo.** API keys go in GitHub Actions secrets or a local `.env`, never in committed files.
6. **Write a CLAUDE.md at the repo root** that records the architecture and decisions, so later sessions in Code or Cowork start with the same context.

## Lessons from the existing tools

The three tools show the same pattern: scholarship works because OpenAlex supplies a single normalised metadata layer, and everything else fails because grey literature has none. Claude Code should read both public repos before starting and confirm these findings.

| Tool | What works | What fails | Take into the new platform |
| --- | --- | --- | --- |
| Insubordinate Finance Terminal (`insubordinate-terminal`, weekly) | OpenAlex keyword, journal and author queries; citation trail for older work; model tagger with relevance scores; weekly review as a GitHub issue with tick boxes; source health page | In run 2026-W40, most IFI and think-tank feeds failed: IMF, UNCTAD, CGD, Eurodad, Chatham House returned 403; BIS, ODI, Finance in Common returned 404. Feed URLs were marked `# check` and never tested. Grey output that week: 2 AfDB press releases. GDELT hit rate limits (429). Page-watchers diff homepage links with a regex per site and break on JavaScript-loaded pages. | Review-by-issue workflow; health reporting with failure streaks; outlet allowlist for news dedupe; the rule that untested sources stay out |
| Soft Currency (`soft-currency-observatory`, monthly) | Anchor works define the topic; OpenAlex and Semantic Scholar works citing the anchors; co-citation candidates; about 7,000-work corpus | No grey or book channel at all. Citation-anchored discovery cannot see material without DOIs. | Anchors and co-citation as an optional per-topic method |
| eNaira Watch (Claude Code, every 5 days) | Discourse coverage: Nairaland, GDELT, Google News, YouTube, Hacker News. 2,600 items | 3 of 2,600 items are official, and all 3 say only that a Central Bank of Nigeria listing page changed, with no document identified | Discourse connectors as opt-in; official pages must yield documents, not change flags |

The three repos also duplicate the same modules (dedupe, tagger, review, build, profile) with drift between them. The new platform should have one copy of each.

## Architecture

The core principle is harvest once, filter many: topics are configuration, connectors are shared, and adding a topic never means writing new scraping code. There are five layers.

```
  [Topic wizard] --writes--> [Topic profiles: topics/<slug>/profile.yaml]
                                        |
                         union of queries, orgs, anchors
                                        v
  [Organisation registry] --> [Shared connectors]  (scholarship, books, working papers,
                                        |           grey, alerts, search API, news,
                                        |           official documents, discourse)
                                        v
                              [Pipeline: normalise -> dedupe -> enrich
                               -> score against every topic]
                                        |
                                        v
                              [Review queue per topic (GitHub issue)]
                                        |              ^
                                        |              | accept/reject decisions
                                        v              | feed back into scoring
                              [Site: topic pages, cross-topic view,
                               source health, digests]
```

1. **Topic wizard** turns seed keywords into an approved profile and a Google Alerts checklist.
2. **Topic profiles** hold everything topic-specific.
3. **Shared connectors and the organisation registry** fetch material once per cycle for all topics.
4. **Pipeline** normalises, deduplicates, enriches and scores each item against each topic, then builds review queues.
5. **Presentation** publishes accepted items per topic, plus health reports and digests.

## Topic profiles and the topic wizard

A topic is a folder with one YAML profile. Everything topic-specific lives there; connectors and pipeline code never contain topic logic.

```
topics/cbdc/profile.yaml
  slug, title, description, status: active | paused
  keywords:        approved terms, each with language (en, fr, pt, ...)
  exclusions:      terms that disqualify an item
  anchors:         DOIs or OpenAlex IDs of key works (optional)
  organisations:   institutions central to the topic, by registry ID
  places:          countries or regions (optional)
  connectors:      which connectors run, with per-topic overrides
  alerts:          generated Google Alert specs + their RSS URLs once created
  cadence:         weekly | monthly
  relevance:       seed text and threshold for scoring
```

The wizard is a CLI command, `monitor new-topic "stablecoins"`, run inside a Claude Code session so a model is available. It works in five steps:

1. **Seed.** Kevin gives 3–10 keywords, optionally anchor works and key organisations.
2. **Expand.** The system proposes related terms from three sources: model suggestions, OpenAlex topics and concepts attached to a first sample of results, and terms that co-occur often in that sample. It also proposes translations where the topic warrants them (French for BCEAO, Portuguese for Brazil).
3. **Approve.** Kevin accepts or rejects each proposed term. Rejections are stored as exclusions-in-waiting so they aren't proposed again.
4. **Alerts (semi-automated).** The system writes a Google Alert spec for each approved query: query string, language, region, sources setting, "deliver to: RSS feed". It outputs a checklist file. Kevin, or Claude in Chrome acting in his account, creates the alerts and pastes back each feed URL. The wizard validates every URL before saving it. Google Alerts has no API, so the system must never try to create alerts by scripting a logged-in browser itself.
5. **Backfill.** The first run pulls 12 months of history from connectors that support date ranges, so the topic page isn't empty on day one.

The wizard ends by opening a pull request that adds the topic folder, so every topic change is reviewable and reversible.

## Connectors

Connectors are shared, topic-agnostic plug-ins. Each takes a list of queries (and optionally organisations, anchors, date range) and returns normalised items. The order of preference for any material is: an aggregator with an API, then a sitemap, then a search API, then page scraping as a last resort.

| Family | Connector | What it supplies | Notes |
| --- | --- | --- | --- |
| Scholarship | OpenAlex | Articles, chapters, some books, reports; keyword, journal, author, citing-anchor and co-citation modes | Free; use the polite pool with an email |
| Scholarship | Semantic Scholar | Citing works for anchors | Optional; key raises rate limits |
| Books | Crossref (book and chapter types) | Academic books with DOIs | Free |
| Books | Google Books | New titles by subject, sorted newest | Free key; noisy, needs strong relevance filtering |
| Books | Open Library | Fallback book metadata and covers | Free |
| Books | Publisher feeds | New and forthcoming titles from chosen presses | Per-press adapters; best early signal for monographs |
| Books | WorldCat | Metadata and holdings enrichment only | Needs institutional OCLC credentials; optional, phase 3 |
| Working papers | RePEc / NEP | IMF, BIS, central bank and university working papers | NEP lists by subject; check feed formats |
| Grey | World Bank Documents API | Reports by query and date | Free |
| Grey | ReliefWeb API | UN agency and NGO reports | Free; check current access terms |
| Grey | Institutional sitemaps | New documents from a registry of organisations | See organisation registry below |
| Grey | Overton or Policy Commons | Indexed policy documents | Paid; only if Edinburgh subscribes |
| Alerts | Google Alerts RSS | Web and news matches per topic query | Created semi-automatically by the wizard |
| Search | Search API (Exa or Brave) | Domain-restricted queries against registry organisations | Small monthly cost; avoids IP blocks on direct fetches |
| News | GDELT DOC API | Global news by query | Rate-limited: one request at a time with backoff |
| News | Outlet RSS | Chosen outlets, filtered by relevance | Every feed tested before use |
| Official | Document scrapers | Central bank circulars, speeches, regulator notices | Must output documents (title, date, PDF link), never "page changed" |
| Discourse | Bluesky, YouTube, forums | Public discussion | Opt-in per topic |
| Podcasts | New Books Network, podcast-search API | Episodes on the topic | Phase 3 |
| Network | Calls for papers and events | CFPs, seminars, conferences | Phase 3 |

**Organisation registry.** One shared file, `registry/organisations.yaml`, lists institutions once with every way to reach them: sitemap URL, RSS feeds, search-API domain, scraper adapter, languages, type (central bank, IFI, NGO, think tank, bank, regulator, publisher). Each entry records `status: tested | untested | broken` and the date last verified. Topics refer to organisations by ID, so the IMF is configured once and used by every topic.

**Fetching constraints.** Many institutional sites block GitHub Actions' datacentre IPs (the 403s in the Terminal). For those, prefer aggregators or the search API over direct fetching. If direct fetching is unavoidable, flag the organisation and propose an alternative (a self-hosted runner on a home machine, or a proxy) for Kevin to decide.

## Pipeline

One harvest serves all topics: connectors run once per cycle with the union of all active topics' queries, and every item is then scored against every topic. An item can belong to several topics.

1. **Normalise** to one item schema: id, title, authors or organisation, date, url, pdf\_url, DOI or ISBN, source\_type, connector, language, abstract or summary, raw metadata.
2. **Deduplicate** across connectors by DOI, ISBN, normalised URL, then fuzzy title plus date. Collapse version pairs (the Zenodo double-DOI duplicates seen in the Terminal) and keep the best record.
3. **Enrich** where cheap: fetch the abstract or first page of PDFs for grey items, resolve redirect links from alert emails and feeds.
4. **Score relevance per topic** in two stages. First an embedding similarity against the topic's seed text and accepted items. Then a model call on the survivors that returns a 0–3 relevance score, theme tags and a one-line reason.
5. **Review queue per topic**: a GitHub issue per topic per cycle, grouped by source type, with tick boxes and a star for featured items, as the Terminal does now. Closing the issue publishes.
6. **Feedback loop.** Accepted and rejected items are stored and fed back into step 4: as positive and negative examples for the embedding stage and as few-shot examples for the model stage. Report per topic how often Kevin overrides the score, so drift is visible.

Items already reviewed are never shown again. Rejections are kept, not deleted, so the feedback loop can learn from them.

## Presentation

One static site, built by GitHub Actions and served on GitHub Pages, with a topic switcher.

- **Home:** list of active topics with counts of new accepted items this cycle.
- **Topic page:** latest accepted items grouped by source type (research, books, working papers, reports and grey, official, news, discourse), featured items first, filters by tag, organisation, type and date.
- **Topic archive and search:** client-side full-text search over all accepted items for that topic.
- **Cross-topic view:** items accepted under more than one topic, which is where adjacent themes show up.
- **Source health:** per connector and per organisation, items returned, failures, failure streaks and last-verified date. Repeated failures open an issue automatically.
- **Digest:** per-topic Markdown digest after each review closes, optionally emailed. Plain links and one-line summaries; news is link-only, never article text.

Design is not a priority in v1. Clean, readable, works on a phone.

## Infrastructure

Python 3.12, a new public or private repo (Kevin decides), GitHub Actions for scheduled runs, GitHub Pages for the site. State is files in the repo for v1: JSONL for items and decisions, YAML for config. Move to SQLite only if the files become unwieldy.

```
monitor/
  CLAUDE.md
  registry/organisations.yaml      shared institution registry
  registry/outlets.yaml            news outlet allowlist
  topics/<slug>/profile.yaml       one folder per topic
  topics/<slug>/alerts.md          wizard's Google Alerts checklist
  engine/connectors/               one module per connector
  engine/pipeline/                 normalise, dedupe, enrich, score, review
  engine/wizard/                   new-topic command
  site/                            templates and static assets
  data/items.jsonl                 all harvested items
  data/decisions/<slug>.jsonl      accept/reject per topic
  data/health/                     per-run health reports
  tests/                           unit tests + recorded connector fixtures
  .github/workflows/               harvest, review, publish
```

Secrets as GitHub Actions secrets: model API key, search API key, optional Semantic Scholar and Google Books keys, and the inbox credentials if email alerts are used. Expected running cost is small: a few pounds a month for the model and search API at Kevin's volume. Claude Code should estimate it after the first runs and report it.

## Build phases

Each phase ends with a demo to Kevin and passes its tests before the next begins. CBDCs is the pilot topic throughout; a second topic is added in phase 2 to prove the platform is generic.

**Phase 0 — Read and plan (one session).** Read both public repos and summarise what to reuse. List anything needed from Kevin. Create the repo skeleton and CLAUDE.md.

- [ ] Written summary of reusable patterns from the two repos
- [ ] Questions for Kevin answered

**Phase 1 — Engine with scholarship and news.** Item schema, connector interface, OpenAlex, GDELT, outlet RSS, Google Alerts RSS, normalise, dedupe, two-stage scoring, review issue, basic site, source health.

- [ ] CBDC topic produces a review issue with at least 30 relevant items
- [ ] Every enabled source shows `ok` on the health page, or is marked broken with a reason
- [ ] Duplicate rate in the review issue below 5%

**Phase 2 — Grey literature, books and the wizard.** Organisation registry with sitemap, search-API and aggregator adapters; World Bank, ReliefWeb, RePEc; Crossref books, Google Books, publisher feeds; official document scrapers for at least three central banks (CBN, CBK, plus one Kevin picks); the `new-topic` wizard with Alert checklist.

- [ ] At least 25 organisations in the registry, each `tested` with a dated verification
- [ ] Second topic (stablecoins) created through the wizard in under an hour of Kevin's time
- [ ] Non-journal items are at least 20% of accepted items across both topics
- [ ] Central bank connectors return named documents with dates and links, never change flags

**Phase 3 — Feedback and extras.** Feedback loop into scoring, cross-topic view, digests by email, podcasts, CFPs and events, optional WorldCat enrichment, optional paid policy index.

- [ ] Override rate (Kevin disagreeing with the score) falls over three cycles on the pilot topic
- [ ] Digest emails arrive after each review closes

## Inputs to request and open questions

Claude Code should ask Kevin for these at the start of phase 0, not guess.

**Material it cannot see from a fresh session:**

- The eNaira Watch code. It isn't in Kevin's public GitHub repos; only its published output was inspected.
- Any notes or decisions from earlier Claude Code and Cowork sessions on the three tools that aren't in the repos.
- The project inbox setup used by the Terminal's email harvester (address, how credentials are stored).
- Kevin's existing Google Alerts, if any, to import rather than duplicate.

**Decisions for Kevin:**

- [ ] Repo name, and public or private
- [ ] Which model API and key to use for scoring and the wizard
- [ ] Which search API to pay for (Exa or Brave), and a monthly cost ceiling
- [ ] Whether Edinburgh library provides access to Overton, Policy Commons or WorldCat credentials
- [ ] Which publishers to watch for books
- [ ] Whether to run a self-hosted runner for sites that block GitHub's IPs
- [ ] Default cadence: weekly or monthly per topic
- [ ] Whether the pilot topic stays CBDCs, and which topic is the second
