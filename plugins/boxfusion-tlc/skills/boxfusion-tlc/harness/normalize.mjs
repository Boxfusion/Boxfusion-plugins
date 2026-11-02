// normalize.mjs — node normalize.mjs <findings.json> > <findings.norm.json>
// Reduces a run's findings.json to the canonical, diffable tuple set (operating-standard.md §3/§8).
// Strips line numbers from anchors, lowercases the path part (keeps #Symbol.Member verbatim),
// validates the closed evidence enum, and sorts canonically. Pure; reads a file path arg (node -I style).
import { readFileSync } from "node:fs";

const BAND = { Critical: 0, High: 1, Medium: 2, Low: 3, Info: 4, None: 4 }; // None≡Info defensively
const LEVELS = new Set([
  "REPRODUCED", "CONFIRMED-IN-LOGS", "VERIFIED-ARTEFACT", "CODE-ONLY", "DATA-ANOMALY", "NOT-ASSESSED",
]);

const stripLines = (s) => s.replace(/:\d+(-\d+)?(?=$|#)/g, ""); // kill any residual line numbers
const normPath = (p) => p.replace(/\\/g, "/").replace(/^\.\//, "").normalize("NFC");
// Lowercase the WHOLE anchor — path AND #Symbol.Member. C# is case-sensitive, but within a single
// path#Type.Member anchor scope two members cannot differ by case alone, so folding is safe and makes
// the diff robust against an operator's identifier-case typo (e.g. #PERSALHelper vs #PersalHelper).
const foldAnchor = (a) => normPath(a).toLowerCase();
// An operator sometimes re-prepends the check id into the anchor ("code-c@none" under check CODE-C,
// "code-j@analyzer" under CODE-J), so the finding_id becomes CODE-C@code-c@none. The anchor carries
// multiplicity, never the check id — strip one leading "<check>@" (any case) so the two runs agree.
const stripDupPrefix = (a, checkId) => {
  const p = `${(checkId || "").toLowerCase()}@`;
  return a.toLowerCase().startsWith(p) ? a.slice(p.length) : a;
};
const levelOf = (r) => {
  const lv = (r.evidence_level || "").replace(/\(.*\)$/, ""); // NOT-ASSESSED(reason) -> NOT-ASSESSED
  if (!LEVELS.has(lv)) throw new Error(`illegal evidence_level "${r.evidence_level}" @ ${r.finding_id}`);
  if (lv === "NOT-ASSESSED" && !r.not_assessed_reason && !/\(.+\)/.test(r.evidence_level || ""))
    throw new Error(`NOT-ASSESSED needs a reason @ ${r.finding_id}`);
  return lv;
};

const rows = JSON.parse(readFileSync(process.argv[2], "utf8"))
  .filter((r) => r && r.finding_id && r.check_id)          // drop stray non-finding objects (e.g. __note)
  .filter((r) => r.non_deterministic !== true);            // drop checks tagged NON-DETERMINISTIC (operating-standard §9)
const out = rows.map((r) => {
  const anchor = stripDupPrefix(foldAnchor(stripLines(r.anchor)), r.check_id);
  const sev = (r.severity === "None") ? "Info" : r.severity; // normalize None→Info
  // A non-scored record (Info / empty-verdict / NOT-ASSESSED) has no remediation plan, so its
  // plan_id is irrelevant to the diff — force it to null so one operator's stray PLAN-xxx on an
  // empty-verdict record does not read as a divergence.
  const planId = (sev === "Info") ? null : (r.plan_id ?? null);
  r = { ...r, severity: sev, plan_id: planId };
  const level = levelOf(r);
  return {
    finding_id: `${r.check_id}@${anchor}`,
    check_id: r.check_id,
    area: r.area,
    anchor,
    evidence_level: level,
    evidence_level_full: r.evidence_level, // keep the reason for the delta report
    severity: r.severity,
    plan_id: r.plan_id, // already nulled for Info above
    fix_order_rank: r.fix_order_rank ?? null,
  };
}).sort((a, b) =>
  (BAND[a.severity] - BAND[b.severity]) ||
  a.area.localeCompare(b.area) ||
  a.check_id.localeCompare(b.check_id) ||
  a.anchor.localeCompare(b.anchor)
);

process.stdout.write(JSON.stringify(out, null, 2));
