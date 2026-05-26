# Test Execution Rules

## 1. Step Execution Model

| Prefix | Meaning |
|--------|---------|
| `NAVIGATE` | Go to a URL |
| `CLICK` | Click an element |
| `TYPE` | Type text into a field |
| `SELECT` | Choose a dropdown option |
| `WAIT` | Wait for a condition |
| `SNAPSHOT` | Take an accessibility snapshot |
| `ASSERT` | Verify something — must produce PASS or FAIL |
| `API` | Make an HTTP request |
| `EXTRACT` | Pull a value from the page or API response |

## 2. Snapshot Rule
Before every CLICK or TYPE, take a snapshot to confirm the element exists. If not found after two attempts, mark FAILED.

## 3. Assertion Rules
- Every ASSERT appears in the report as `[PASS]` or `[FAIL]`
- Include the actual value observed next to every assertion
- A `(BLOCKING)` assertion failure stops the entire test

## 4. Report Format
Reports saved to `test-reports/YYYY-MM-DD/<plan-name>.md`:
```
# Report: <Plan Title>
**Date:** YYYY-MM-DD HH:MM UTC
**Plan:** test-plans/<folder>/<filename>.md
**Spec:** test-plans/<folder>/<filename>.spec.ts
**Execution Mode:** playwright-script | ai-repair | hybrid
**Result:** PASSED | FAILED | PARTIAL
**Duration:** Xs

## Summary
| Total Steps | Passed | Failed | Skipped |
|-------------|--------|--------|---------|

## Step Results
### TC-NN — <Title>
**Mode:** playwright-script | ai-repair (patched <step>)
**Duration:** Xs
- [PASS] / [PASS (repaired)] / [FAIL] <assertion or step summary>
```

## 5. Pass / Fail Criteria
- **PASSED** — all assertions pass
- **FAILED** — one or more `(BLOCKING)` assertions fail, OR >50% fail
- **PARTIAL** — some non-blocking assertions fail but majority pass

## 6. Dashboard Update
After every test run, regenerate the central dashboard:
```bash
node scripts/build-dashboard.js
```
The dashboard ([test-reports/index.html](../test-reports/index.html)) is auto-generated from every plan in `test-plans/` and every report under `test-reports/`. **Never hand-edit it.** It includes:
- A GitHub-style activity heatmap (last 52 weeks)
- A flows table with sparklines and `NEW` / `UPDATED` / `no .spec.ts yet` badges
- A day-grouped run timeline

A flow is flagged `UPDATED` when its `.md` or `.spec.ts` `mtime` is newer than the most recent report for that plan — the visual cue that the plan has changed since it was last validated.

## 7. Allure Report Generation
After every test run, regenerate and open the Allure report from ALL reports:
```bash
rm -rf allure-results
node scripts/generate-allure-results.js
npx allure generate allure-results --clean -o allure-report
npx allure open allure-report
```

## 8. Hybrid Execution Model (Playwright-first, AI-repair fallback)

Every plan has a paired `.spec.ts` beside it (`test-plans/<folder>/<name>.spec.ts`). The plan is canonical; the spec is a derived, self-healing artefact.

### Scaffold conventions
Specs are written by `/CreateTest` using `@playwright/test`. Selectors are **captured live** via MCP browser recording at create time — `/CreateTest` walks each plan step against the real app, snapshots the accessibility tree, and emits the resolved locator directly. Each TC becomes one `test()` block; each plan step becomes a labelled section:
```ts
// STEP 3: TYPE username field with `admin`
await page.getByRole('textbox', { name: 'Username' }).fill('admin');
```
Markers and their meaning:
- `// STEP N: <verbatim step text>` — maps the spec line back to plan step N. Required on every action.
- `// TODO[selector]: <hint>` — appears **only** when MCP recording couldn't locate the element after 2 retries; AI-repair resolves it on first run.
- `// TODO[assertion]: <hint>` — same, for non-trivial `expect(...)` calls.
- `// FRAGILE: <reason>` — appears when only a 3-level CSS chain matched. A signal to harden the app's accessibility, not a runtime concern.

### Execution flow
1. `node scripts/run-plan.js <plan>.md` — runs Playwright, emits a JSON summary.
2. If `status === "no-spec"` → Claude scaffolds the spec from the plan, then re-invokes the runner.
3. If `status === "passed"` → report is already written by the runner; proceed to Allure.
4. If any test failed → for each failure:
   - Read the error `location.line` from the JSON.
   - Open MCP browser, replay the test up to the failing step using prior steps in the spec, snapshot.
   - Resolve the real selector from the snapshot.
   - **Edit only the failing line** in the .spec.ts (leave `// STEP` and `// TODO` comments updated to reflect the new selector — drop the `TODO[...]:` marker when a real selector is locked in).
   - Re-run that single test with `node scripts/run-plan.js <plan>.md --grep "TC-NN" --no-report`.
   - Up to 2 repair attempts per failing test before giving up.
5. After repairs settle, run the full plan once more to write the final report, then run Allure.
6. **Hub sync is a separate skill (`/submit-test-results`) — not part of the run loop.** `/RunTest` rebuilds the local dashboard + Allure and stops. The user invokes `/submit-test-results` when they're ready to publish.

### Repair logging
- Each test that succeeded only after repair is reported as `**Mode:** ai-repair (patched STEP N)`.
- Each repaired line should still match its `// STEP N:` comment so the diff is auditable.

### When to regenerate vs repair
| Situation | Action |
|---|---|
| One selector drifted | AI-repair patches that line only |
| New step added to the .md plan | Regenerate the scaffold for that TC (`/CreateTest` overwrites with confirmation) |
| Whole page restructured | Regenerate the spec; AI-repair will then re-anchor selectors on next run |
