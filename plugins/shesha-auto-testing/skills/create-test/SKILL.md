---
name: create-test
description: Author a new markdown test plan at test-plans/<folder>/<name>.md AND a paired Playwright spec at test-plans/<folder>/<name>.spec.ts with real selectors recorded live via MCP browser. Trigger phrases include "create a test", "create a test plan", "new test for X", "test plan for Y", "add a test that...". The user provides only a title and a numbered list of high-level steps. The skill pulls App URL, environment, and credentials from CLAUDE.md, expands each step into full action steps per test-plans/RULES.md, matches the style of existing plans, AND walks each step against the real app via Playwright MCP to capture the resolved locator before writing the spec. Steps that can't be located after 2 retries fall back to a `// TODO[selector]:` marker for AI-repair on first run. The plan + spec are executed later by the run-test skill — this skill authors only, it does NOT run.
---

# Create Test

Author a plan AND its paired Playwright spec with **real selectors recorded live**. Do not run the test as part of the run-test loop — this skill only authors.

## Input format

Ask the user once, using exactly this format, then stop asking:

```
Title: <feature name, e.g. "Create Service Request">
Folder: <optional — leave blank to auto-pick>
Steps:
1. <high-level step>
2. <high-level step>
3. ...
```

**If their first message already supplies a title + numbered steps, skip the prompt and generate immediately.**

Never ask for App URL, credentials, environment, today's date, or file path.

## Folder selection

- Match the title to an existing folder under `test-plans/` (e.g. *"Create Service Request"* → `service-requests/`, *"Login"* → `auth/` if it exists).
- If nothing fits, propose a new kebab-case folder name and confirm before creating it.

## Pre-flight (mandatory, in order)

1. Read `CLAUDE.md` → App URL, Environment, Credentials, today's date.
2. Read `test-plans/RULES.md` → prefixes, snapshot rule, assertion rules, hybrid execution model (§8).
3. Read the closest neighbour plan in the target folder. Match its style, depth, and section order exactly. If the folder is brand new, use `test-plans/cases/create-case.md` as the canonical example.
4. **Verify Admin credentials in `CLAUDE.md`.** The recorded login helper embeds the username and password directly, so empty or placeholder values (`<TODO>`, `change-me`, empty) produce a broken spec. If the Admin row is missing or placeholder, stop and tell the user:

   > No usable Admin credentials in `CLAUDE.md`. Run `/test-setup` (which validates the credentials table), or add a row to the Credentials section manually:
   > ```
   > | Admin | <username> | <password> |
   > ```
   > Then re-run this skill.

   Do not invent placeholder credentials and continue.

5. **Probe Playwright MCP (headless).** Call `mcp__playwright__browser_navigate` with `url: "about:blank"`. If it errors, stop and tell the user:

   > Playwright MCP server is not reachable. The recording loop needs it to capture selectors live. Check `.mcp.json` and ensure the Playwright MCP server is running, then re-run this skill.

6. **Verify headless mode.** Run `claude mcp list 2>&1` and check the `playwright` line for the `--headless` flag. The recording loop must not pop a visible browser window — the whole point of this skill is silent, background recording. If the flag is absent, ask once:

   > The Playwright MCP is registered without `--headless`, so recording will open a visible Chromium window. Re-register it now in headless mode? Runs:
   > ```
   > claude mcp remove playwright
   > claude mcp add playwright -- npx -y @playwright/mcp@latest --headless
   > ```

   On yes, run both commands, then re-probe (`mcp__playwright__browser_navigate` with `url: "about:blank"`) before continuing. On no, continue but warn in the finishing reply that the recording ran headed.

## Generation — markdown plan

Expand the user's bullets into a `TC-NN` structure per `test-plans/RULES.md`:

1. Expand each user step into a `TC-NN` block with prefixed actions (`NAVIGATE`, `CLICK`, `TYPE`, `SELECT`, `WAIT`, `SNAPSHOT`, `ASSERT`, `API`, `EXTRACT`).
2. Auto-prepend a login TC if any step needs auth — use the credentials from `CLAUDE.md`.
3. Snapshot before every `CLICK` or `TYPE`.
4. Every `ASSERT` is observable from a snapshot; exactly one `(BLOCKING)` assertion per critical TC.
5. Estimated duration: ~15s per simple TC, ~60s for create-and-submit, ~120s end-to-end. Round to 30s.
6. Save to `test-plans/<folder>/<kebab-title>.md`. If the file exists, ask before overwriting.

## Generation — paired Playwright spec via MCP recording

After the `.md` is written, drive the real app via Playwright MCP to capture every selector live, then emit the `.spec.ts`. This replaces the old "guess + TODO marker" scaffold.

**Recording runs headless / in the background.** Pre-flight step 6 verifies the Playwright MCP is registered with `--headless` so no Chromium window pops up while the loop walks the app. Do not call `mcp__playwright__browser_resize` or any tool that depends on a visible viewport — every selector resolution must work off the accessibility snapshot, not screen coordinates. Status updates to the user are limited to short text lines ("Recording TC-02 step 3 / 7 …") — never imply "watch the browser" in any prompt.

### Recording loop — per TC, sequentially

For each `TC-NN` in the plan, in plan order:

1. **Open a fresh page.** `mcp__playwright__browser_navigate` to `APP_URL` (or the URL the first `NAVIGATE` step specifies).
2. **Login if the TC needs auth** (anything beyond the very first TC, or any TC referencing protected pages). Record the login helper *once* per spec — reuse for every TC after that.
   1. Snapshot the page (`mcp__playwright__browser_snapshot`).
   2. Find the username field: `role=textbox` with accessible `name` matching `/username|email|user/i`. If multiple textboxes and none match by name, take the first textbox above the password field.
   3. `mcp__playwright__browser_type` the admin username from `CLAUDE.md`.
   4. Snapshot, find the password field: `role=textbox` with `name=/password/i` (or a textbox whose `type=password` attribute is exposed in the snapshot).
   5. `mcp__playwright__browser_type` the admin password.
   6. Snapshot, find the submit button: `role=button` with `name=/sign in|log in|submit/i`.
   7. `mcp__playwright__browser_click` it.
   8. `mcp__playwright__browser_wait_for` until network is idle or a known logged-in element appears.
   9. Record each resolved locator into the `loginAsAdmin` helper.
3. **For each subsequent plan step**, in plan order, apply the prefix → MCP mapping below. After resolving a locator, **call the corresponding MCP action to verify it actually works** before emitting the line into the spec — if MCP click/type fails, fall through to the next selector strategy.
4. After the last step of the TC, call `mcp__playwright__browser_close` to reset state, then start the next TC.

### Prefix → MCP action + emitted spec line

| Plan prefix | MCP recording step | Emitted spec line |
|---|---|---|
| `NAVIGATE <url>` | `_navigate` to `<url>` | `await page.goto('<url>');` |
| `SNAPSHOT — <desc>` | none (Playwright auto-waits at runtime) | `// SNAPSHOT: <desc>` (comment only) |
| `CLICK <hint>` | `_snapshot`, resolve locator per priority list, `_click` to verify | `await page.<resolved-locator>.click();` |
| `TYPE <field> with \`<value>\`` | `_snapshot`, resolve label/placeholder/textbox locator, `_type` with `<value>` to verify | `await page.<resolved-locator>.fill('<value>');` |
| `SELECT <dropdown> — choose <option>` | `_snapshot`, resolve trigger, `_click`, `_snapshot` menu, resolve option, `_click` | Two lines: trigger click then option click |
| `WAIT for <condition>` | none (observable from later steps) | `await expect(page.<resolved-locator>).toBeVisible();` if condition names a visible element, else `await page.waitForLoadState('networkidle');` |
| `ASSERT <claim>` | `_snapshot`, resolve, observe value | `await expect(page.<resolved-locator>).<matcher>;` |
| `ASSERT (BLOCKING) <claim>` | same as ASSERT, but emit `// ASSERT (BLOCKING): <claim>` above the expect line | same as ASSERT |
| `API <method> <url>` | none — emitted as a network call | `await page.request.<method>('<url>');` |
| `EXTRACT <thing>` | `_snapshot`, resolve, capture text | `const <var> = await page.<resolved-locator>.textContent();` |

### Selector priority

When the snapshot is in hand, resolve the failing line's element by walking this list until one matches:

1. **`role` + accessible `name`** matching the hint (case-insensitive substring). Emit `page.getByRole('<role>', { name: '<exact accessible name>' })`. This is the preferred form — stable across redesigns.
2. **`label` text** matching the hint. Emit `page.getByLabel('<exact label>')`. Use for form inputs with `<label for>` associations.
3. **Visible text node** matching the hint. Emit `page.getByText('<exact text>')`. Use for non-interactive verifications.
4. **`data-testid`** on the element (or its nearest interactive ancestor). Emit `page.getByTestId('<id>')`.
5. **Last resort**: a 3-level CSS chain from the snapshot's parent path (e.g. `[data-testid="grid"] >> button.add`). Emit the locator AND a `// FRAGILE: <reason>` comment one line above. Cap the chain at 3 levels.

For each candidate, **call the corresponding MCP action to verify it works** (`_click` for buttons/links, `_type` for fields). If the MCP call fails (ref stale, multiple matches, not visible), drop to the next strategy.

### Bounded fallback

If 2 strategy retries fail to locate an element, emit the heuristic guess with a `// TODO[selector]: <hint>` marker one line above. Move on — don't block the rest of the recording. AI-repair will resolve the TODO on first `/RunTest`.

Cap the recording effort per TC at ~2 minutes wall-clock. If a TC takes longer (recording stuck on the same step), fall through to the heuristic emission for the remaining steps with TODO markers. Note the count of fallback markers in the finishing reply.

### Spec file structure

The emitted `.spec.ts` template — keep this shape exactly:

```ts
// AUTO-RECORDED from test-plans/<folder>/<kebab-title>.md
// The .md plan is canonical. AI-repair will patch failing lines in this file.
// Do not hand-edit unless you are also updating the .md plan.

import { test, expect, Page } from '@playwright/test';

const APP_URL = '<from CLAUDE.md>';
const ADMIN = { user: '<from CLAUDE.md>', password: '<from CLAUDE.md>' };

async function loginAsAdmin(page: Page) {
  await page.goto(APP_URL);
  // STEP login.1: <verbatim>
  await page.<recorded-locator-for-username>.fill(ADMIN.user);
  // STEP login.2: <verbatim>
  await page.<recorded-locator-for-password>.fill(ADMIN.password);
  // STEP login.3: <verbatim>
  await page.<recorded-locator-for-submit>.click();
  await page.waitForLoadState('networkidle');
}

test.describe('<Plan Title>', () => {
  test('TC-01: <TC title>', async ({ page }) => {
    // STEP 1: <verbatim plan step>
    <action line>

    // STEP 2: <verbatim plan step>
    <action line>

    // ASSERT (BLOCKING) <assertion>
    await expect(<resolved-locator>).<matcher>;
  });

  test('TC-02: <TC title>', async ({ page }) => {
    await loginAsAdmin(page);
    // ... recorded steps ...
  });
});
```

### Hard rules for the spec

- Every action line MUST have a `// STEP N: <verbatim plan step>` comment immediately above it. AI-repair uses these as anchors when it has to patch a line.
- Use `getByRole` / `getByLabel` / `getByText` first; raw CSS only as the last-resort fallback with a `// FRAGILE:` comment above it.
- The `loginAsAdmin` helper at the top is recorded once per spec and reused — do not re-record per TC.
- Save to `test-plans/<folder>/<kebab-title>.spec.ts`. If the file exists, ask before overwriting (same prompt as the `.md`).

## Finishing reply

One line, nothing else:

> Created `test-plans/<folder>/<name>.md` + `<name>.spec.ts` with **<N> recorded selectors, <K> fallback TODO markers**. Run with `/RunTest <name>`. (If K>0, expect AI-repair to resolve those K lines on first run.)
