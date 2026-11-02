// diff-findings.mjs — node diff-findings.mjs A.norm.json B.norm.json manifestA.json manifestB.json
// The acceptance test (operating-standard.md §0). Passes iff the two normalized runs agree on the
// canonical tuple {finding_id|anchor|evidence_level|severity|plan_id} AND on the fix-order list,
// over the capability intersection of the two manifests. Exit 0 = converged, 1 = diverged.
import { readFileSync } from "node:fs";

const J = (p) => JSON.parse(readFileSync(p, "utf8"));
const [A, B, MA, MB] = process.argv.slice(2).map(J);

// present capabilities = tool presence + top-level capability flags
const caps = (m) => {
  const c = m.capabilities || {};
  const tools = Object.entries(c.tools || {}).filter(([, v]) => v && v.present).map(([k]) => k);
  const flags = Object.entries(c).filter(([k, v]) => k !== "tools" && v && v.present).map(([k]) => k);
  return new Set([...tools, ...flags]);
};
const capA = caps(MA), capB = caps(MB);
const intersection = [...capA].filter((x) => capB.has(x));

const key = (r) => `${r.finding_id}|${r.anchor}|${r.evidence_level}|${r.severity}|${r.plan_id}`;
const assessed = (arr) => new Set(arr.filter((r) => r.evidence_level !== "NOT-ASSESSED").map(key));
const sa = assessed(A), sb = assessed(B);
const onlyA = [...sa].filter((x) => !sb.has(x));
const onlyB = [...sb].filter((x) => !sa.has(x));

// Fix-order compares only SCORED, actionable findings — exclude Info / NOT-ASSESSED
// (non-actionable records can differ in presence without being a real divergence).
const order = (arr) =>
  arr.filter((r) => r.fix_order_rank != null && r.severity !== "Info" && r.severity !== "None"
                    && r.evidence_level !== "NOT-ASSESSED")
     .slice().sort((x, y) => x.fix_order_rank - y.fix_order_rank)
     .map((r) => r.finding_id).join(",");
const fix_order_match = order(A) === order(B);

const commitA = MA.repo?.commit_sha, commitB = MB.repo?.commit_sha;
const same_commit = commitA && commitA === commitB;

const pass = onlyA.length === 0 && onlyB.length === 0 && fix_order_match && same_commit;
console.log(JSON.stringify({
  pass,
  same_commit,
  manifest_intersection: intersection,
  onlyA, onlyB,
  fix_order_match,
  note: "Findings whose required capabilities are not in both manifests are excluded from the diff; " +
        "equalize manifests (install gitleaks, restore the same DB, provision a low-priv user) then re-run. " +
        (same_commit ? "" : "WARNING: commits differ — not comparable."),
}, null, 2));
process.exit(pass ? 0 : 1);
