(function () {
  "use strict";

  // No backend involved: this just builds a pre-filled "new issue" URL and
  // opens it. GitHub handles auth (you're submitting under your own
  // account) and storage (the issue itself). See CLAUDE.md, "Handling a
  // new-topic request" for what happens to it after that.
  var REPO = "kevinpdonovan/topic-monitor";

  var form = document.getElementById("new-topic-form");
  if (!form) return;

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var seed = document.getElementById("new-topic-seed").value.trim();
    var notes = document.getElementById("new-topic-notes").value.trim();
    if (!seed) return;

    var title = "New topic request: " + seed;
    var body = [
      "## Seed terms",
      "",
      seed,
      "",
      "## Notes",
      "",
      notes || "_none_",
      "",
      "---",
      "Submitted via the site request form. A Claude Code session will follow up here with proposed related terms and a couple of clarifying questions before building the topic profile.",
    ].join("\n");

    var url =
      "https://github.com/" + REPO + "/issues/new" +
      "?title=" + encodeURIComponent(title) +
      "&body=" + encodeURIComponent(body) +
      "&labels=" + encodeURIComponent("new-topic");

    window.open(url, "_blank", "noopener");
  });
})();
