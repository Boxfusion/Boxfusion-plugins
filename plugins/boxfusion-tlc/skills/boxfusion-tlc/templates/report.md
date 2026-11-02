<!--
Report shape. Target about 1,300 lines for a system with 50-70 findings.
- Critical and high findings in full (templates/finding.md, full form).
- Medium findings as compact 10-12-line blocks (templates/finding.md, compact form): no "Why" paragraph, point to the root cause or learning digest.
- Low findings as one-line rows, each pointing to its digest pattern or root cause.
- The summary table has a Task column and no status or test columns. Tests live in the Test index appendix.
- No per-finding PM lines that only point back to the PM section.
- Duplicates and numbering notes go in Appendix B.
- Severity is not sequence: the Architect review holds the sequence; never raise a severity so a finding lands first.
- Unproven critical findings are worded "the configuration allows..." / "the code allows..." until reproduced.
- Use one parent work item name throughout.
-->

# <System name> diagnosis report

**Date:** <date> · **Environment inspected:** <QA copy / development database / approved production copy, date; say if transactional tables are empty> · **Telemetry:** <App Insights resource, period, sampling note> · **Shesha:** <version> · **Run:** quick | deep | trial | area: <area> · **Code at:** <commit>

> How to read this report: the summary is for everyone. "Questions for the BA" and "Concerns for the PM" need answers from those people. Each finding explains what happens and how to fix it; the full write-ups also explain why it is a problem. Developers new to these topics should read the "Why this is a problem" parts and the learning digest. Nothing here names or blames anyone: these are properties of the system, not of people.

## 0. Test coverage

<From diagnosis/00-test-readiness.md, in plain English. This comes first because every finding's proof depends on it.>

| | State | Notes |
|---|---|---|
| Back-end integration tests | <covered / partly / none> | <source → test project map; entities and services with tests; builds? runs? pass/fail/skip> |
| E2E tests | <harness present / partial / none> | <journeys and roles covered; test logins; portal version used for UI results> |
| Runs locally | yes / no | <what blocks it> |
| Runs in CI on pull requests | yes / no | <pipeline, results published?> |

**Brought up to standard:** <what was added on `tlc/test-coverage` (test projects, tests, e2e plans and specs); baseline pass/fail; tests that fail on the untouched system (these are findings); what still can't be tested and why>.

## 1. Summary

<Five to eight sentences: the overall state, the two or three things that matter most, and what to do first.>

**What to do first:** <three to six bullets, in sequence order, from the Architect review: urgent containment, the decisions that gate other work, the first request to the IT Manager>.

<For a quick run: one short paragraph on what a deep run would add (App Insights, production checks if justified).>

| # | Finding | Severity | Evidence | Size | Task |
|---|---|---|---|---|---|
| <ID> | <title> | <sev> | <level> | S/M/L | T<n> |

**Evidence levels:**
- **REPRODUCED:** we made it happen, with a test that fails for the right reason.
- **CONFIRMED-IN-LOGS:** production telemetry shows it.
- **VERIFIED-ARTEFACT:** a checked fact about a file or configuration (including scanner and compile results).
- **CODE-ONLY:** seen in the code, not yet shown to happen.
- **DATA-ANOMALY:** odd data with no proven cause yet.

*Please pass this on to the previous developer(s) of this system, if applicable.* The "Why this is a problem" and "What good looks like" sections are written to help them.

## 2. Architect review

### A. Root causes

| # | Root cause | Findings it explains | Structural fix (framework-native) | Standing regression guard |
|---|---|---|---|---|
| RC1 | <plain-English cause> | <IDs> | <fix> | <e.g. the authorisation inventory test in CI> |

### B. Fix sequence

<Phases with dependencies, the decisions that gate them, and what can run in parallel. Severity says how bad; sequence says what comes first.>

### C. Emergency shortcuts register

| Shortcut | Why it's an emergency | Native end state | Follow-up trigger |
|---|---|---|---|

<Note what is not a shortcut: documented framework caveats, operational steps such as credential rotation.>

### D. Ranking challenges

<Raise / lower / keep with a note, each with its reason. Applied re-ranks are already reflected in the summary table.>

## 3. Questions for the BA

<Grouped by topic, numbered. Each one says which finding it unblocks and why the answer matters.>

## 4. Concerns for the PM

<Risk, release and sequencing, rollback (pre-import exports for packages; one open package per form), changes users will notice, effort (rough), dependencies between fixes, skills the team needs, escalations (IT Manager, Shesha team, other owners), cross-project disclosure for framework-wide issues.>

## 5. Findings

<Critical and high findings in rank order, in full (templates/finding.md, full form). Then medium findings as compact blocks (templates/finding.md, compact form). Then low findings as one-line rows: ID · title · fix · task · digest pattern or RC. The evidence detail lives in diagnosis/findings/<area>.md: point to it, don't copy it.>

## 6. Shesha framework issues

<One line per framework defect, with a pointer to diagnosis/SHESHA-TEAM-REPORT.md, which carries the full reproduction, a ready-to-paste Claude prompt, whether to log an SR (with copy-paste wording), and the candidates still to reproduce before sending.>

## 7. What we checked and found fine

<One line per area.>

## 8. Learning digest

<Patterns that recur across the system, each with: the pattern, how many places, why it hurts, the better habit, and the findings it covers. Medium findings point here instead of repeating "why". These make good team learning topics.>

## 9. Not checked, and why

<Inputs that were missing: no App Insights access, no production copy, mobile repo not provided, portal feed token expired, and so on.>

## 10. Agreed plan and board

<After the walkthrough: the fix groups in order, and the parent work item {SystemName}-TLC-Fixes with its consolidated tasks (findings covered by each, phase, dependencies, BA/PM needs, size, PR branches), follow-up items (from the shortcuts register), and the PR rules. In a trial run, label it "Proposal only: nothing is created".>

## 11. Decision log

| Date | Finding | Decision | Reason |
|---|---|---|---|

## Appendix A: Test index

One row per finding with a test. "Fails because" is the one-line assertion message: proof only when it shows the finding's behaviour, not a login or setup error.

| Finding | Reproducing test | Result today | Fails because | Regression test (after the fix) |
|---|---|---|---|---|
| <ID> | <test name and path, or —> | fails / passes / partly disproves / not run | <message> | <test to keep or add> |

## Appendix B: Duplicates and numbering

<Merged-away IDs as `duplicate → <id>`, ID ranges per analyst, and any numbering notes.>

## Appendix C: Environment and method

<Recon summary, data-safety measures taken, fact-check corrections, query and file references.>
