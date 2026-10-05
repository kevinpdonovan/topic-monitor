# Marks store (Cloudflare Worker)

Keeps reading marks — bookmarks, hidden items, low-quality marks, muted
sources — in one place so they follow you between browsers, instead of
being stranded in whichever browser's `localStorage` you made them in.

The site keeps a `localStorage` copy as a cache and offline fallback. This
Worker is the shared source of truth.

## Why this exists

A static GitHub Pages site can't write to shared storage without either a
credential in the browser or a backend. Putting a GitHub token in the
browser would mean repo-write access sitting in `localStorage` on a public
site. This Worker is the smaller blast radius: its write key grants access
to this one key-value store and nothing else.

## Shape

```
GET  /marks/<slug>   -> { bookmarked, hidden, demoted, mutedSources, updated }
PUT  /marks/<slug>   -> same shape; requires X-Marks-Key
```

Reads are open — the topic pages and the items being marked are already
public, and leaving reads open means a browser shows the right marks with
no setup at all. Writes need the key, because the Worker URL is visible in
the site's JavaScript and otherwise anyone could wipe the marks.

## Cost

Free tier, with a lot of headroom. Workers Free allows 100,000
requests/day; Workers KV allows 100,000 reads, 1,000 writes and 1 GB
stored per day. Expected use is roughly one read per page load and one
write per mark — tens per day against those limits. Free limits reset at
00:00 UTC and failing operations error rather than silently billing.

## Deploying

Needs Node (for `wrangler`). From this directory:

```bash
npx wrangler login                        # browser OAuth, approve in the page
npx wrangler kv namespace create MARKS    # paste the printed id into wrangler.toml
npx wrangler secret put WRITE_KEY         # paste a long random string
npx wrangler deploy
```

`wrangler deploy` prints the Worker URL. Put it in `site/config.yaml` as
`marks_api`, rebuild, and the site will start using it. The same
`WRITE_KEY` value is entered once per browser, via the "Connect" control
in the page's Sources panel — it's stored in that browser's
`localStorage` and sent as `X-Marks-Key` on writes.

## Rotating the key

`npx wrangler secret put WRITE_KEY` with a new value, then re-enter it in
each browser. Stored marks are unaffected.
