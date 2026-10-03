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

  var app = document.getElementById("app");
  if (!app) return;
  var itemsUrl = app.getAttribute("data-items-url");

  var allItems = [];
  var state = { q: "", quality: new Set(["high", "medium", "low", "unscored"]), view: "all" };

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

  function qualityKey(item) {
    return item.quality || "unscored";
  }

  function matchesSearch(item, q) {
    if (!q) return true;
    var hay = [
      item.title, item.venue, item.organisation,
      (item.authors || []).join(" "), (item.tags || []).join(" "), item.abstract,
    ].join(" ").toLowerCase();
    return hay.indexOf(q.toLowerCase()) !== -1;
  }

  function filtered() {
    return allItems.filter(function (it) {
      return state.quality.has(qualityKey(it)) && matchesSearch(it, state.q);
    });
  }

  function groupByType(items) {
    var groups = {};
    items.forEach(function (it) {
      var t = it.source_type || "article";
      (groups[t] = groups[t] || []).push(it);
    });
    return SOURCE_TYPE_ORDER.filter(function (t) {
      return groups[t];
    }).map(function (t) {
      return [t, groups[t]];
    });
  }

  function renderItemLine(it) {
    var meta = [it.venue, it.date, it.organisation].filter(Boolean).join(" &middot; ");
    var authors = it.authors && it.authors.length ? it.authors.join(", ") : it.organisation;
    var q = qualityKey(it);
    var badges = '<span class="badge quality-' + q + '">' + (QUALITY_LABELS[q] || "Unscored") + "</span>";
    if (it.featured) badges += '<span class="badge featured">featured</span>';
    return (
      "<li><a class=\"title\" href=\"" + escapeHtml(it.url) + "\">" + escapeHtml(it.title) + "</a> " +
      badges +
      '<div class="meta">' + escapeHtml(authors || "") + (meta ? " &middot; " + meta : "") + "</div></li>"
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

  function renderAll(items) {
    if (!items.length) return '<p class="muted">No items match the current filters.</p>';
    return renderGroups(items);
  }

  function renderByMonth(items) {
    if (!items.length) return '<p class="muted">No items match the current filters.</p>';
    var byMonth = {};
    items.forEach(function (it) {
      (byMonth[it.month] = byMonth[it.month] || []).push(it);
    });
    var months = Object.keys(byMonth).sort().reverse();
    return months.map(function (m) {
      return (
        '<h2 class="month-heading">' + monthLabel(m) + " (" + byMonth[m].length + ")</h2>" +
        renderGroups(byMonth[m])
      );
    }).join("");
  }

  function render() {
    var items = filtered();
    var countEl = document.getElementById("result-count");
    if (countEl) countEl.textContent = items.length + " of " + allItems.length + " items";
    var resultsEl = document.getElementById("results");
    if (resultsEl) resultsEl.innerHTML = state.view === "month" ? renderByMonth(items) : renderAll(items);
  }

  function wireControls() {
    var controls = document.getElementById("controls");
    if (controls) controls.hidden = false;

    var searchInput = document.getElementById("search-input");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        state.q = searchInput.value;
        render();
      });
    }

    var checkboxes = document.querySelectorAll(".quality-filter input[type=checkbox]");
    checkboxes.forEach(function (cb) {
      cb.addEventListener("change", function () {
        if (cb.checked) state.quality.add(cb.value);
        else state.quality.delete(cb.value);
        render();
      });
    });

    var viewButtons = document.querySelectorAll(".view-toggle button");
    viewButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.view = btn.getAttribute("data-view");
        viewButtons.forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        render();
      });
    });
  }

  if (!itemsUrl) return;
  fetch(itemsUrl)
    .then(function (r) {
      return r.json();
    })
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
