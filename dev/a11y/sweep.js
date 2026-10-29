// Accessibility sweep: run axe-core over every page in both themes.
//
// 1. In a scratch folder:  npm install axe-core@4.10.2
// 2. Copy node_modules/axe-core/axe.min.js to app/web/static/_axe.min.js
//    (git ignores it through .git/info/exclude; delete it afterwards).
// 3. Start the app against a scratch library (never your real one), open it in the browser
//    pane or Edge, and paste this whole file into the console.
// 4. Read the result: an object of "theme route" -> list of problems. Empty lists are clean.
//
// Switching theme starts CSS transitions; the pause below lets them finish so axe reads the
// final colours rather than a half-way mix.
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  await new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/static/_axe.min.js";
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
  const routes = ["/", "/photos", "/videos", "/trips", "/review/near_duplicate", "/review/exact_duplicate",
    "/review/blurry", "/review/screenshot", "/review/marked", "/removed", "/organize", "/settings", "/scan", "/search"];
  const tags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
  const out = {};
  for (const theme of ["light", "dark"]) {
    document.documentElement.dataset.theme = theme;
    await sleep(700);
    for (const route of routes) {
      location.hash = route;
      await sleep(1800);
      const result = await axe.run(document, { runOnly: { type: "tag", values: tags } });
      out[`${theme} ${route}`] = result.violations.map(
        (v) => `${v.id} [${v.impact}] x${v.nodes.length}: ${v.nodes[0].target.join(" ").slice(0, 80)}`
      );
    }
  }
  console.table(Object.entries(out).map(([page, problems]) => ({ page, problems: problems.length ? problems.join("; ") : "clean" })));
  return out;
})();
