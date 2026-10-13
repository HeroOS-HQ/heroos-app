// Test results for the end-to-end suite: every check is recorded with its
// evidence, nothing is skipped silently, and the run fails if any check fails.
import { writeFileSync } from "node:fs";
import { join } from "node:path";

export function createReport() {
  const results = [];
  let section = "setup";
  const report = {
    results,
    section(name) {
      section = name;
      console.log(`\n== ${name}`);
    },
    /** Records a check. `ok` must be a boolean outcome actually observed. */
    check(id, name, ok, detail = "") {
      results.push({ section, id, name, ok: Boolean(ok), detail: String(detail).slice(0, 600) });
      console.log(`${ok ? "PASS" : "FAIL"}  [${id}] ${name}${detail && !ok ? ` — ${String(detail).slice(0, 300)}` : ""}`);
      return Boolean(ok);
    },
    /** A check that could not run in this environment (stated, never counted as passed). */
    notRun(id, name, reason) {
      results.push({ section, id, name, ok: null, detail: reason });
      console.log(`N/A   [${id}] ${name} — ${reason}`);
    },
    get failed() {
      return results.filter((r) => r.ok === false);
    },
    write(dir, extra = {}) {
      const passed = results.filter((r) => r.ok === true).length;
      const notRun = results.filter((r) => r.ok === null).length;
      const summary = { passed, failed: report.failed.length, notRun, total: results.length, ...extra };
      writeFileSync(join(dir, "results.json"), JSON.stringify({ summary, results }, null, 2));
      const lines = [
        "# HeroOS local end-to-end results",
        "",
        `${passed} passed, ${summary.failed} failed, ${notRun} not run (of ${results.length}).`,
        "",
        "| Section | ID | Check | Result | Detail |",
        "| --- | --- | --- | --- | --- |",
        ...results.map((r) =>
          `| ${r.section} | ${r.id} | ${r.name.replace(/\|/g, "\\|")} | ${r.ok === null ? "not run" : r.ok ? "pass" : "**FAIL**"} | ${r.detail.replace(/\|/g, "\\|").replace(/\n/g, " ")} |`,
        ),
      ];
      writeFileSync(join(dir, "results.md"), `${lines.join("\n")}\n`);
      return summary;
    },
  };
  return report;
}
