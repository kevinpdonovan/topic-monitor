/**
 * topic-monitor marks store.
 *
 * Holds per-topic reading marks (bookmarks, hidden items, low-quality
 * marks, muted sources) so they follow Kevin between browsers instead of
 * being stranded in one browser's localStorage. The site still keeps a
 * localStorage copy as a cache and offline fallback; this is the shared
 * source of truth.
 *
 *   GET  /marks/<slug>   -> { bookmarked, hidden, demoted, mutedSources, updated }
 *   PUT  /marks/<slug>   -> same shape; requires the write key
 *
 * Reads are open. The topic pages are public and so are the items being
 * marked, so there is nothing to protect on the read side, and leaving it
 * open means a browser shows the right marks with no setup at all.
 *
 * Writes require X-Marks-Key. The Worker URL is visible in the site's
 * JavaScript, so without a key anyone could wipe the marks. The key is a
 * Worker secret — it grants nothing beyond this store, unlike a GitHub
 * token, which is why this design was preferred over writing to the repo
 * directly from the browser.
 */

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const MAX_BODY_BYTES = 256 * 1024;

const EMPTY = { bookmarked: [], hidden: [], demoted: [], mutedSources: [], updated: null };

function corsHeaders(env, request) {
  // Reflect the caller's origin only when it's on the allow-list, so the
  // response stays usable from the Pages site and from a local preview
  // during development, without being readable-by-anyone-with-credentials.
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const origin = request.headers.get("Origin") || "";
  const allow = allowed.includes(origin) ? origin : allowed[0] || "*";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Marks-Key",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(body, status, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...extra },
  });
}

/** Keep only the shape we expect, so a malformed or hostile body can't
 *  grow the stored object without bound or smuggle unexpected fields. */
function sanitise(input) {
  const ids = (v) =>
    Array.isArray(v)
      ? [...new Set(v.filter((x) => typeof x === "string" && /^[0-9a-f]{10}$/.test(x)))].slice(0, 5000)
      : [];
  const names = (v) =>
    Array.isArray(v)
      ? [...new Set(v.filter((x) => typeof x === "string" && x.length <= 200))].slice(0, 500)
      : [];
  return {
    bookmarked: ids(input.bookmarked),
    hidden: ids(input.hidden),
    demoted: ids(input.demoted),
    mutedSources: names(input.mutedSources),
    updated: new Date().toISOString(),
  };
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env, request);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);
    const match = url.pathname.match(/^\/marks\/([^/]+)$/);
    if (!match) {
      return json({ error: "not found" }, 404, cors);
    }
    const slug = match[1];
    if (!SLUG_RE.test(slug)) {
      return json({ error: "bad slug" }, 400, cors);
    }
    const key = `marks:${slug}`;

    if (request.method === "GET") {
      const stored = await env.MARKS.get(key, { type: "json" });
      return json(stored || EMPTY, 200, cors);
    }

    if (request.method === "PUT") {
      if (!env.WRITE_KEY) {
        return json({ error: "worker not configured: WRITE_KEY unset" }, 503, cors);
      }
      if (request.headers.get("X-Marks-Key") !== env.WRITE_KEY) {
        return json({ error: "bad or missing write key" }, 401, cors);
      }
      const raw = await request.text();
      if (raw.length > MAX_BODY_BYTES) {
        return json({ error: "body too large" }, 413, cors);
      }
      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (e) {
        return json({ error: "invalid json" }, 400, cors);
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return json({ error: "expected an object" }, 400, cors);
      }
      const clean = sanitise(parsed);
      await env.MARKS.put(key, JSON.stringify(clean));
      return json(clean, 200, cors);
    }

    return json({ error: "method not allowed" }, 405, cors);
  },
};
