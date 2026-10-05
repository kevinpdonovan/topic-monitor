(function () {
  "use strict";

  var SOURCE_TYPE_LABELS = {
    article: "Research articles",
    chapter: "Book chapters",
    book: "Books",
    working_paper: "Working papers",
    report: "Reports and grey literature",
    policy_document: "Policy and official documents",
    news: "News",
    discourse: "Discourse",
    podcast: "Podcasts",
  };
  var SOURCE_TYPE_ORDER = Object.keys(SOURCE_TYPE_LABELS);
  var QUALITY_LABELS = { high: "High", medium: "Medium", low: "Low", unscored: "Unscored" };

  // Corrections (hide / mark-low / mute-source) live in this browser only.
  // They are a *view* preference until they're sent back to the repo and
  // applied to data/decisions/<slug>.jsonl — that's what the "Send
  // corrections" button is for. Said plainly in the UI so the distinction
  // isn't a surprise. See CLAUDE.md, "Applying corrections from the site".
  var REPO = "kevinpdonovan/topic-monitor";
  var MAX_EXPORTED = 40; // keep the pre-filled issue URL a sane length

  var app = document.getElementById("app");
  if (!app) return;
  var itemsUrl = app.getAttribute("data-items-url");
  var slug = app.getAttribute("data-slug") || "topic";
  var storageKey = "topic-monitor:" + slug;

  var allItems = [];
  var state = { q: "", quality: new Set(["high", "medium", "low", "unscored"]), view: "all", showHidden: false, bookmarkedOnly: false };
  var prefs = { hidden: [], demoted: [], mutedSources: [], bookmarked: [], quality: null };

  // --- storage -------------------------------------------------------
  // localStorage throws outright in some privacy modes, so every access is
  // guarded; losing corrections is survivable, a page that won't render is not.
  function loadPrefs() {
    try {
      var raw = window.localStorage.getItem(storageKey);
      if (!raw) return;
      var parsed = JSON.parse(raw);
      prefs.hidden = parsed.hidden || [];
      prefs.demoted = parsed.demoted || [];
      prefs.bookmarked = parsed.bookmarked || [];
      prefs.mutedSources = parsed.mutedSources || [];
      prefs.quality = parsed.quality || null;
    } catch (e) { /* no stored prefs, carry on with defaults */ }
  }

  function savePrefs() {
    try {
      prefs.quality = Array.from(state.quality);
      window.localStorage.setItem(storageKey, JSON.stringify(prefs));
    } catch (e) { /* storage unavailable — corrections stay for this page view only */ }
  }

  function toggleIn(list, value) {
    var i = list.indexOf(value);
    if (i === -1) list.push(value); else list.splice(i, 1);
    return i === -1;
  }

  // --- item helpers --------------------------------------------------
  function sourceOf(item) { return item.venue || item.organisation || "(no source)"; }
  function isHidden(item) { return prefs.hidden.indexOf(item.id) !== -1; }
  function isBookmarked(item) { return prefs.bookmarked.indexOf(item.id) !== -1; }
  function isMuted(item) { return prefs.mutedSources.indexOf(sourceOf(item)) !== -1; }
  function qualityKey(item) {
    if (prefs.demoted.indexOf(item.id) !== -1) return "low";
    return item.quality || "unscored";
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function monthLabel(monthKey) {
    if (monthKey === "undated") return "Undated";
    var parts = monthKey.split("-");
    var d = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
    return d.toLocaleString(undefined, { month: "long", year: "numeric" });
  }

  function matchesSearch(item, q) {
    if (!q) return true;
    var hay = [
      item.title, item.venue, item.organisation,
      (item.authors || []).join(" "), (item.tags || []).join(" "), item.abstract,
    ].join(" ").toLowerCase();
    return hay.indexOf(q.toLowerCase()) !== -1;
  }

  function visibleItems() {
    // In bookmarked view, show exactly the bookmarks (search still applies).
    // Deliberately not intersected with the quality filter or suppression:
    // a bookmark is an explicit "keep this", and having one silently vanish
    // because a quality checkbox is unticked elsewhere would be baffling.
    if (state.bookmarkedOnly) {
      return allItems.filter(function (it) {
        return isBookmarked(it) && matchesSearch(it, state.q);
      });
    }
    return allItems.filter(function (it) {
      var suppressed = isHidden(it) || isMuted(it);
      if (suppressed && !state.showHidden) return false;
      if (!suppressed && !state.quality.has(qualityKey(it))) return false;
      return matchesSearch(it, state.q);
    });
  }

  function suppressedCount() {
    return allItems.filter(function (it) { return isHidden(it) || isMuted(it); }).length;
  }

  // --- rendering -----------------------------------------------------
  function groupByType(items) {
    var groups = {};
    items.forEach(function (it) {
      var t = it.source_type || "article";
      (groups[t] = groups[t] || []).push(it);
    });
    return SOURCE_TYPE_ORDER.filter(function (t) { return groups[t]; })
      .map(function (t) { return [t, groups[t]]; });
  }

  function renderItemLine(it) {
    var meta = [it.venue, it.date, it.organisation].filter(Boolean).join(" &middot; ");
    var authors = it.authors && it.authors.length ? it.authors.join(", ") : it.organisation;
    var q = qualityKey(it);
    var suppressed = isHidden(it) || isMuted(it);

    var marked = isBookmarked(it);
    var badges = '<span class="badge quality-' + q + '">' + (QUALITY_LABELS[q] || "Unscored") + "</span>";
    if (marked) badges += '<span class="badge bookmarked">★ bookmarked</span>';
    if (it.featured) badges += '<span class="badge featured">featured</span>';
    if (isHidden(it)) badges += '<span class="badge suppressed">hidden</span>';
    else if (isMuted(it)) badges += '<span class="badge suppressed">source muted</span>';

    // Bookmarking stays available on a suppressed item: the sensible
    // recovery from "hid it, then realised I wanted it" shouldn't require
    // restoring it first.
    var bookmarkBtn = '<button class="act' + (marked ? " on" : "") + '" data-act="bookmark" data-id="' + it.id +
      '" title="' + (marked ? "Remove bookmark" : "Bookmark this item") + '">' +
      (marked ? "★ bookmarked" : "☆ bookmark") + "</button>";

    var actions = suppressed
      ? bookmarkBtn + '<button class="act" data-act="restore" data-id="' + it.id + '" title="Bring this back">restore</button>'
      : bookmarkBtn +
        '<button class="act" data-act="hide" data-id="' + it.id + '" title="Hide this item">hide</button>' +
        (q === "low"
          ? '<button class="act" data-act="undemote" data-id="' + it.id + '" title="Undo low-quality mark">unmark low</button>'
          : '<button class="act" data-act="demote" data-id="' + it.id + '" title="Mark as low quality">mark low</button>') +
        '<button class="act" data-act="mute" data-source="' + escapeHtml(sourceOf(it)) + '" title="Mute every item from this source">mute source</button>';

    return (
      '<li class="' + (suppressed ? "is-suppressed" : "") + '">' +
      '<a class="title" href="' + escapeHtml(it.url) + '">' + escapeHtml(it.title) + "</a> " + badges +
      '<div class="meta">' + escapeHtml(authors || "") + (meta ? " &middot; " + meta : "") + "</div>" +
      '<div class="item-actions">' + actions + "</div>" +
      "</li>"
    );
  }

  function renderGroups(items) {
    return groupByType(items).map(function (pair) {
      var type = pair[0], group = pair[1];
      return (
        "<h2>" + (SOURCE_TYPE_LABELS[type] || type) + " (" + group.length + ")</h2>" +
        '<ul class="items">' + group.map(renderItemLine).join("") + "</ul>"
      );
    }).join("");
  }

  // Research articles dominate the corpus (200 of 219 at the time of
  // writing), so a single stream buries everything else 200 items down the
  // page. Articles take the left column; chapters, books, working papers,
  // grey literature, official documents and news share the right, which
  // keeps the two sides roughly even and puts the non-journal material —
  // the stuff this project exists to surface — where it can be seen.
  var LEFT_COLUMN_TYPES = ["article"];

  function renderColumns(items) {
    var left = items.filter(function (it) { return LEFT_COLUMN_TYPES.indexOf(it.source_type) !== -1; });
    var right = items.filter(function (it) { return LEFT_COLUMN_TYPES.indexOf(it.source_type) === -1; });
    // A lone column reads better full width than squeezed into half.
    if (!left.length || !right.length) return renderGroups(items);
    return '<div class="columns"><div class="col">' + renderGroups(left) +
           '</div><div class="col">' + renderGroups(right) + "</div></div>";
  }

  function renderByMonth(items) {
    var byMonth = {};
    items.forEach(function (it) { (byMonth[it.month] = byMonth[it.month] || []).push(it); });
    return Object.keys(byMonth).sort().reverse().map(function (m) {
      return '<h2 class="month-heading">' + monthLabel(m) + " (" + byMonth[m].length + ")</h2>" + renderColumns(byMonth[m]);
    }).join("");
  }

  function renderSourceFilter() {
    var counts = {};
    allItems.forEach(function (it) {
      var s = sourceOf(it);
      counts[s] = (counts[s] || 0) + 1;
    });
    var names = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
    return names.map(function (name) {
      var muted = prefs.mutedSources.indexOf(name) !== -1;
      return (
        '<li><span class="src-name' + (muted ? " muted" : "") + '">' + escapeHtml(name) + "</span>" +
        '<span class="src-count">' + counts[name] + "</span>" +
        '<button class="act" data-act="' + (muted ? "unmute" : "mute") + '" data-source="' + escapeHtml(name) + '">' +
        (muted ? "unmute" : "mute") + "</button></li>"
      );
    }).join("");
  }

  function render() {
    var items = visibleItems();
    var countEl = document.getElementById("result-count");
    if (countEl) {
      var n = suppressedCount();
      countEl.textContent = state.bookmarkedOnly
        ? items.length + " bookmarked item" + (items.length === 1 ? "" : "s")
        : items.length + " of " + allItems.length + " items" + (n ? " · " + n + " suppressed" : "");
    }

    var bookmarkToggle = document.getElementById("bookmarked-toggle");
    if (bookmarkToggle) {
      bookmarkToggle.textContent = "★ Bookmarked (" + prefs.bookmarked.length + ")";
      bookmarkToggle.classList.toggle("active", state.bookmarkedOnly);
      bookmarkToggle.hidden = prefs.bookmarked.length === 0 && !state.bookmarkedOnly;
    }

    var toggle = document.getElementById("show-hidden");
    if (toggle) {
      toggle.textContent = state.showHidden ? "Hide suppressed" : "Show suppressed (" + suppressedCount() + ")";
      // Suppression is meaningless in the bookmarked view, which ignores it.
      toggle.hidden = suppressedCount() === 0 || state.bookmarkedOnly;
    }
    var sendBtn = document.getElementById("send-corrections");
    if (sendBtn) {
      sendBtn.hidden = suppressedCount() === 0 && prefs.demoted.length === 0 && prefs.bookmarked.length === 0;
    }

    var srcList = document.getElementById("source-list");
    if (srcList) srcList.innerHTML = renderSourceFilter();

    var resultsEl = document.getElementById("results");
    if (!resultsEl) return;
    resultsEl.innerHTML = items.length
      ? (state.view === "month" ? renderByMonth(items) : renderColumns(items))
      : '<p class="muted">No items match the current filters.</p>';
  }

  // --- corrections export --------------------------------------------
  function correctionsIssueUrl() {
    function titlesFor(ids) {
      return ids.slice(0, MAX_EXPORTED).map(function (id) {
        var it = allItems.filter(function (x) { return x.id === id; })[0];
        return "- `" + id + "` — " + (it ? it.title : "(not in current list)");
      }).join("\n");
    }
    var lines = ["Marks made while reading the " + slug + " page.", ""];
    if (prefs.bookmarked.length) {
      // Bookmarks aren't a correction — they're Kevin's reading list — but
      // they ride along so they aren't stranded in one browser. Applied as
      // featured: true, which the site already renders.
      lines.push("## Bookmarked — feature these (" + prefs.bookmarked.length + ")", "",
        titlesFor(prefs.bookmarked), "");
    }
    if (prefs.hidden.length) {
      lines.push("## Reject these items (" + prefs.hidden.length + ")", "", titlesFor(prefs.hidden), "");
    }
    if (prefs.demoted.length) {
      lines.push("## Mark these low quality (" + prefs.demoted.length + ")", "", titlesFor(prefs.demoted), "");
    }
    if (prefs.mutedSources.length) {
      lines.push("## Stop harvesting these sources", "",
        prefs.mutedSources.map(function (s) { return "- " + s; }).join("\n"), "");
    }
    if (prefs.hidden.length > MAX_EXPORTED || prefs.demoted.length > MAX_EXPORTED) {
      lines.push("_(list truncated at " + MAX_EXPORTED + " per section)_", "");
    }
    lines.push("---", "Sent from the site. Apply per CLAUDE.md, \"Applying corrections from the site\".");
    return "https://github.com/" + REPO + "/issues/new" +
      "?title=" + encodeURIComponent("Marks from the site: " + slug) +
      "&body=" + encodeURIComponent(lines.join("\n")) +
      "&labels=" + encodeURIComponent("corrections");
  }

  // --- wiring --------------------------------------------------------
  function wireControls() {
    var controls = document.getElementById("controls");
    if (controls) controls.hidden = false;

    var searchInput = document.getElementById("search-input");
    if (searchInput) {
      searchInput.addEventListener("input", function () { state.q = searchInput.value; render(); });
    }

    document.querySelectorAll(".quality-filter input[type=checkbox]").forEach(function (cb) {
      cb.checked = state.quality.has(cb.value);
      cb.addEventListener("change", function () {
        if (cb.checked) state.quality.add(cb.value); else state.quality.delete(cb.value);
        savePrefs();
        render();
      });
    });

    var viewButtons = document.querySelectorAll(".view-toggle button");
    viewButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.view = btn.getAttribute("data-view");
        viewButtons.forEach(function (b) { b.classList.toggle("active", b === btn); });
        render();
      });
    });

    var showHidden = document.getElementById("show-hidden");
    if (showHidden) {
      showHidden.addEventListener("click", function () { state.showHidden = !state.showHidden; render(); });
    }

    var bookmarkToggle = document.getElementById("bookmarked-toggle");
    if (bookmarkToggle) {
      bookmarkToggle.addEventListener("click", function () {
        state.bookmarkedOnly = !state.bookmarkedOnly;
        render();
      });
    }

    var sendBtn = document.getElementById("send-corrections");
    if (sendBtn) {
      sendBtn.addEventListener("click", function () {
        window.open(correctionsIssueUrl(), "_blank", "noopener");
      });
    }

    var sourcesToggle = document.getElementById("sources-toggle");
    if (sourcesToggle) {
      sourcesToggle.addEventListener("click", function () {
        var panel = document.getElementById("source-panel");
        if (panel) panel.hidden = !panel.hidden;
      });
    }

    // One delegated handler for every per-item / per-source action button.
    document.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest("button.act") : null;
      if (!btn) return;
      var act = btn.getAttribute("data-act");
      var id = btn.getAttribute("data-id");
      var source = btn.getAttribute("data-source");

      if (act === "bookmark") toggleIn(prefs.bookmarked, id);
      else if (act === "hide") toggleIn(prefs.hidden, id);
      else if (act === "demote") toggleIn(prefs.demoted, id);
      else if (act === "undemote") toggleIn(prefs.demoted, id);
      else if (act === "mute" || act === "unmute") toggleIn(prefs.mutedSources, source);
      else if (act === "restore") {
        // Restore undoes whichever suppression applied — the item may be
        // hidden directly, muted via its source, or both.
        var item = allItems.filter(function (x) { return x.id === id; })[0];
        if (prefs.hidden.indexOf(id) !== -1) toggleIn(prefs.hidden, id);
        if (item && prefs.mutedSources.indexOf(sourceOf(item)) !== -1) toggleIn(prefs.mutedSources, sourceOf(item));
      } else return;

      savePrefs();
      render();
    });
  }

  loadPrefs();
  if (prefs.quality) state.quality = new Set(prefs.quality);

  if (!itemsUrl) return;
  fetch(itemsUrl)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      allItems = data;
      wireControls();
      render();
    })
    .catch(function () {
      // items.json fetch failed (e.g. the page was opened as a local
      // file:// page, which blocks same-directory fetches under CORS) --
      // leave the server-rendered, non-interactive list in #results alone.
    });
})();
