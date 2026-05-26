---
name: run-test
description: Execute one or more markdown test plans from test-plans/ locally using the Playwright-first / AI-repair hybrid runner. Trigger phrases include "run test X", "run the X test", "run test-plans/<folder>/<name>.md", "execute the call log test", "run the test plan for Y". When the plan name is ambiguous (multiple matches, or none specified), the skill lists every plan with its last-run status and asks the user to pick one or more (`1,3,5`, `1-3`, or `all`). The skill invokes scripts/run-plan.js (which runs the paired .spec.ts via @playwright/test); on failure it falls back to AI-driven MCP browser execution to repair the failing line in the spec, then re-runs. After 2 failed AI-repair attempts it auto-classifies the failure by signature — stale-plan symptoms trigger a plan/spec fix, business-logic symptoms auto-log a bug under test-reports/bugs/ and the run continues. Writes a markdown report to test-reports/YYYY-MM-DD/, regenerates test-reports/index.html and the Allure report. **Does NOT push to the hub** — the user invokes /submit-test-results separately when they're ready to publish.
---

# Run Test

Execute one or more markdown test plans via their paired Playwright specs, with AI repair as a fallback. Plans are authored by the `create-test` skill — this skill **only runs them**, and **does NOT push to the hub** (that's `/submit-test-results`'s job).

## Pre-flight (mandatory, in order)

1. Read `CLAUDE.md` completely
2. Read `test-plans/RULES.md` completely (especially §8 Hybrid Execution)
3. Identify the target plan(s) (see "Identifying the plan(s)" below)
4. Read each selected plan file
5. Read the paired `.spec.ts` if it exists

Do not invoke the runner before all five are done.

## Identifying the plan(s) — ask when ambiguous

Resolve in this order:

1. **Explicit path** — e.g. *"run test-plans/cases/create-case.md"* → confirm in one line, proceed.
2. **Single-match filename hint** — e.g. *"run the call log test"* → glob `test-plans/**/*call*log*.md`. If exactly one match, confirm and proceed.
3. **Zero matches** — present the full plan list and ask the user (see format below).
4. **Multiple matches** — present the matching subset and ask the user.
5. **User says "all"** — run every `.md` under `test-plans/` (excluding `RULES.md`) sequentially; treat each as a separate invocation of the run loop.

### Ask-the-user list format

When asking, always include each plan's last-run status. Pull it from the most recent `test-reports/<YYYY-MM-DD>/<plan-name>.md`'s `**Result:**` line. If never run, show `—`.

```
Multiple plans match (or none specified). Pick one or more (comma-separated, ranges, or "all"):

  1. calls/create-call-log              [last: PASSED 2026-05-20]
  2. cases/create-call-log-entry        [last: PARTIAL 2026-05-19]
  3. cases/create-case                  [last: PASSED 2026-05-20]
  4. service-requests/create-service-request       [last: —]
  5. service-requests/create-service-request-v2    [last: FAILED 2026-05-18]
```

Parse `1,3,5` (specific picks), `1-3` (range), or `all` (every entry). Confirm the resolved list back in one line before running:

> Resolved to: `cases/create-case.md`, `service-requests/create-service-request-v2.md` — running sequentially.

Run plans **sequentially**, not in parallel. Within-plan parallelism comes from Playwright workers; cross-plan parallelism risks rate-limiting the test app and tangles the dashboard.

## Execution — Playwright-first (per plan)

For each selected plan, run:
```bash
node scripts/run-plan.js <plan>.md
```

Parse the JSON emitted on stdout. The runner emits one of:

| `status` | Meaning | Next action |
|---|---|---|
| `no-spec` | Paired `.spec.ts` does not exist | Tell the user — recommend `/CreateTest` (it now records selectors live, so re-running them is cheap). Do NOT scaffold a TODO-marker spec from this skill; that's no longer the create flow. |
| `passed` | All tests passed | Update dashboard + Allure, done |
| `partial` / `failed` | One or more tests failed | Begin AI-repair loop |
| `error` | Runner itself crashed | Report the error to the user; do not retry blindly |

## AI-repair loop (when tests fail)

For each failing test in the runner's `tests[]` array:

1. **Locate the failing line.** Read `error.location.line` from the JSON; open the .spec.ts and read ±5 lines around it. The `// STEP N:` comment immediately above maps to a plan step.
2. **Replay context.** Use Playwright MCP tools (`mcp__playwright__browser_navigate`, then walk earlier steps of the test) to reach the same point the script was at when it failed. Use the working selectors already in the spec — only the failing line is broken.
3. **Snapshot.** `mcp__playwright__browser_snapshot` to get the accessibility tree.
4. **Resolve the real selector.** From the snapshot, find the element the failing line was trying to interact with. Prefer `getByRole({ name: ... })` / `getByLabel(...)` / `getByText(...)`. Fall back to `getByTestId` or a stable CSS selector if no semantic match exists.
5. **Patch the spec.** Use `Edit` to replace ONLY the failing line. Drop the `// TODO[selector]:` / `// TODO[assertion]:` marker on the line above (the selector is no longer a guess). Keep the `// STEP N:` comment intact.
6. **Re-run just that test:**
   ```bash
   node scripts/run-plan.js <plan>.md --grep "TC-NN" --no-report
   ```
7. If it now passes → mark the test as `ai-repair (patched STEP N)` for the report.
   If it still fails → try one more time (different selector strategy).
   If two attempts fail → stop repair for that test; it will go through the "fix plan vs log bug" flow.

After all repairs settle (or are abandoned), re-run the FULL plan once more to refresh the markdown report with the final state:
```bash
node scripts/run-plan.js <plan>.md
```

## Repair guardrails

- **Never edit `// STEP N:` comments.** They map back to plan steps; AI repair only touches the action/assertion line below.
- **Never edit the .md plan during repair.** The plan is canonical. If the plan itself is wrong (renamed feature, removed field), that's the "fix plan" path below, not repair.
- **Cap repair attempts at 2 per test.** Beyond that, it's an app bug or a fundamentally stale plan.
- **Never bypass `(BLOCKING)` failures.** If a BLOCKING assertion fails after repair, the test stays FAILED.

## Report

The runner writes the report at `test-reports/<today>/<plan-name>.md` on the final pass. Verify it exists. Do NOT hand-edit `test-reports/index.html` — it is auto-generated in the next step.

Each Playwright invocation also writes `test-results/junit.xml` (industry-standard JUnit format) for CI consumption. The `/submit-test-results` skill copies this into `<hub>/projects/dep/test-results/junit.xml` alongside the markdown reports and Allure output. See the **Test Artifacts** table in CLAUDE.md for the full map.

## Dashboard + Allure (mandatory, after every run)

The central dashboard is regenerated from the full `test-plans/` and `test-reports/` trees so new flows, updated plans, and the activity heatmap stay in sync. Then Allure is rebuilt. From the repo root:

```bash
node scripts/build-dashboard.js
rm -rf allure-results
node scripts/generate-allure-results.js
npx allure generate allure-results --clean --single-file -o allure-report
```

Or in one shot: `npm run report:all` (skips opening Allure — run `npx allure open allure-report` separately).

## Hub sync — NOT this skill

Hub sync is a separate skill. After every run, `/RunTest` rebuilds the local dashboard + Allure and stops. When the user is ready to publish to the central hub, they invoke `/submit-test-results`.

Do NOT call `npm run report:hub` from this skill. Every finishing reply ends with a reminder pointing the user at `/submit-test-results`.

## On unrecoverable failure — auto-classify, then act

When a test still fails after 2 AI-repair attempts (or the failure was never selector-shaped), do **not** prompt the user. Read the failure signature off the Playwright JSON + the latest MCP snapshot, classify into one of three buckets, and act.

### Classification

| Bucket | Signature | Action |
|---|---|---|
| **Stale plan** | `TimeoutError` on a selector; "expected to find element"; the page renders but the named element is absent; `strict mode violation` (multiple matches); the failing step's described element doesn't appear in the snapshot at all | **Fix the plan** branch — see below |
| **Business-logic / app bug** | HTTP 5xx in network log; the action succeeded technically but the app surfaced a user-visible error (toast/banner/inline error); the form posted and the expected created entity does not appear; an assertion about *value* (not visibility) is wrong; unhandled JS exception in console; navigation went somewhere unexpected after a working click | **Log a bug** branch — see below |
| **Ambiguous** | Signals from both buckets, or no clear network/UX evidence either way (e.g. the test hung with no console output) | Fall back to the original prompt: ask the user once which branch to take |

When in doubt between Stale-plan and Business-logic, prefer **Business-logic** — it is the safer default: it never destroys author intent, and a wrong call just means a bug entry that a dev triages and dismisses.

### Fix-the-plan branch (stale-plan signature)

1. Identify the stale step from the `// STEP N:` comment near the failing line.
2. From the MCP snapshot, find what the page actually looks like now (renamed button, moved field, new wizard step before the action).
3. Edit `test-plans/<folder>/<name>.md` to correct the affected step(s). Keep the structure (prefixes, snapshots, assertions); only change what the snapshot says is now true.
4. Regenerate the affected TC block in the `.spec.ts` (overwrite that single test; preserve every other test block verbatim — do not touch them).
5. Re-run that test only:
   ```bash
   node scripts/run-plan.js <plan>.md --grep "TC-NN" --no-report
   ```
6. If it now passes, continue to the final full re-run. If it still fails with the same signature, escalate to Log-a-bug (with category `plan-correction-failed`).
7. Summarise the plan change in one bullet list for the finishing reply.

### Log-a-bug branch (business-logic signature)

1. Write `test-reports/bugs/<today>-<plan-kebab>.md` containing:
   - **Plan**: `<path to plan>`
   - **Failing TC**: `TC-NN — <title>`
   - **Step**: `<verbatim from // STEP N: comment>`
   - **Expected**: `<from the plan's ASSERT line or step description>`
   - **Actual**: `<one-line, from the snapshot or network log>`
   - **Suspected category**: one of `business-logic | infra | data | other`
   - **Playwright error**: code-fenced excerpt from the runner JSON
   - **Snapshot / screenshot**: path under `test-results/artifacts/` (Playwright writes one automatically on failure)
   - **Suspected cause**: one line — your best guess
2. Mark the test as FAILED in the run's markdown report (the runner already does this on the final pass — do not hand-edit).
3. **Keep going.** Do not stop the run; do not skip the dashboard step. The bug is captured; the rest of the suite should still complete.
4. The dashboard generator (`scripts/build-dashboard.js`) already scans `test-reports/bugs/` and surfaces a `bug` link in the affected flow's row. No manual dashboard edits.

### Ambiguous-signal branch (fallback only)

Only when both buckets fire or neither does, ask the user, in one message:

> Test failed at TC-NN, step N: *<one-line summary>*. Signals are mixed.
> My read: classify as **<your best guess>** because *<reason>*. Proceed with that, or pick the other?

Honour their answer. Do not loop the question.

### Logged bugs persist

A logged bug is permanent state — it lives in `test-reports/bugs/` until a dev triages it (move to `test-reports/bugs/closed/` or delete after fixing the app). A subsequent green run does NOT delete the bug file. The dashboard's flow row only links bugs whose name contains the plan kebab, so closing a bug means moving it out of the scanned folder. When the user next runs `/submit-test-results`, any new bugs sync to the hub.

## Finishing reply (per plan)

One concise summary per plan that was run:

> Ran `test-plans/<folder>/<name>.md` → **<RESULT>** in `<duration>` (mode: `<playwright-script | hybrid>`). Report: `test-reports/<today>/<name>.md`. Local dashboard + Allure rebuilt.
> *(if any tests were repaired)* AI-repair patched **N selector(s)** in `<name>.spec.ts`: <one-line list>.
> *(if failed and resolved)* Followed up by **<fixing the plan | logging bug at test-reports/bugs/...>**.
>
> **Next step:** run `/submit-test-results` to push this run to the central hub.

When the user ran "all" or multiple plans, append a one-line aggregate after the per-plan replies:

> All-plans summary: <X passed> / <Y failed> / <Z partial> over <total>s. `/submit-test-results` when ready.
