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

1. Read `CLAUDE.md` → App URL, Environment, today's date. (Credentials are **not** in `CLAUDE.md` — they live in the gitignored `.env`; see step 4.)
2. Read `test-plans/RULES.md` → prefixes, snapshot rule, assertion rules, hybrid execution model (§8).
3. Read the closest neighbour plan in the target folder. Match its style, depth, and section order exactly. If the folder is brand new, use `test-plans/cases/create-case.md` as the canonical example.
4. **Verify the required environment + role credentials in `.env`.** Credentials must never be hardcoded — the recorded spec reads them from the environment, and the recording loop below needs the real values to drive the login form. See **Environments & roles** below for the full model. Concretely, before recording:
   - Work out which **role(s)** the plan's steps need to log in as (default `ADMIN`) and which **environment** to record against (from `CLAUDE.md` → Environments, or the active `TEST_ENV` in `.env`).
   - Read `.env` at the repo root and confirm: a site URL resolves for that environment (`<ENV>_APP_URL` or `APP_URL`), and for every needed role, `<ROLE>_USERNAME` and `<ROLE>_PASSWORD` are present and non-placeholder (`<TODO>`, `change-me`, `CHANGE-ME`, empty).
   - **If a needed role or environment is missing**, auto-register it (don't just fail): add the role/environment to `CLAUDE.md`'s Environments/Roles tables and add the blank keys to `.env.example`, then stop and tell the user which keys to fill in `.env`:

     > Registered `<ROLE>`/`<ENV>` in `CLAUDE.md` + `.env.example`. Add the real value(s) to `.env` (gitignored, never committed):
     > ```
     > <ROLE>_USERNAME=<username>
     > <ROLE>_PASSWORD=<password>
     > <ENV>_APP_URL=<url>
     > ```
     > Then re-run this skill. (Or run `/test-setup` to be prompted for them.)

   Do not invent placeholder credentials and continue. Never write credential values into the plan, the spec, `.env.example`, or `CLAUDE.md` — only into `.env`.

5. **Probe Playwright MCP (headless).** Call `mcp__playwright__browser_navigate` with `url: "about:blank"`. If it errors, stop and tell the user:

   > Playwright MCP server is not reachable. The recording loop needs it to capture selectors live. Check `.mcp.json` and ensure the Playwright MCP server is running, then re-run this skill.

6. **Verify headless mode.** Run `claude mcp list 2>&1` and check the `playwright` line for the `--headless` flag. The recording loop must not pop a visible browser window — the whole point of this skill is silent, background recording. If the flag is absent, ask once:

   > The Playwright MCP is registered without `--headless`, so recording will open a visible Chromium window. Re-register it now in headless mode? Runs:
   > ```
   > claude mcp remove playwright
   > claude mcp add playwright -- npx -y @playwright/mcp@latest --headless
   > ```

   On yes, run both commands, then re-probe (`mcp__playwright__browser_navigate` with `url: "about:blank"`) before continuing. On no, continue but warn in the finishing reply that the recording ran headed.

## Environments & roles

The suite supports **multiple sites** (QA, Test, Staging …) and **multiple login roles** (Admin, Manager, standard User …). Secrets never live in a committed file — only the non-secret *registry* of what exists lives in `CLAUDE.md`; the actual values live in the gitignored `.env`.

**Environments (sites).** `CLAUDE.md` → `## Environments` lists each environment name and the env var holding its URL. `.env` holds the real URLs and an active `TEST_ENV`:

```
# .env
TEST_ENV=qa
QA_APP_URL=https://qa.example.com
TEST_APP_URL=https://test.example.com
```

`playwright.config.ts` resolves `baseURL` from `APP_URL`, else `<TEST_ENV>_APP_URL`. The recording loop records against the active environment; specs use **relative** paths so switching `TEST_ENV` re-points every test.

**Roles.** `CLAUDE.md` → `## Credentials` lists each role name and the two env vars holding its credentials. `.env` holds the real values, one pair per role:

```
# .env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=…
MANAGER_USERNAME=bob
MANAGER_PASSWORD=…
```

The spec's `loginAs(page, '<ROLE>')` helper reads `<ROLE>_USERNAME` / `<ROLE>_PASSWORD` at run time. A plan step names the role abstractly (*log in as a Manager*); it never contains a literal credential.

**Auto-register.** When a plan needs a role or environment that isn't defined yet, add it to the `CLAUDE.md` table(s) and to `.env.example` (blank), then stop and ask the user to fill the real value into `.env` (pre-flight step 4). Never commit the value.

## Generation — markdown plan

Expand the user's bullets into a `TC-NN` structure per `test-plans/RULES.md`:

1. Expand each user step into a `TC-NN` block with prefixed actions (`NAVIGATE`, `CLICK`, `TYPE`, `SELECT`, `WAIT`, `SNAPSHOT`, `ASSERT`, `API`, `EXTRACT`).
2. Auto-prepend a login TC if any step needs auth. Name the **role** the test logs in as (default *Admin*) — e.g. ``NAVIGATE the app and log in as an Admin``. In the **plan** (`.md`), refer to the credentials abstractly (*the admin username* / *the manager password*) — never write a literal username or password into the plan. The real values are supplied from `.env` per role at recording/run time. If the plan needs a role/environment not yet registered, follow **Environments & roles → Auto-register**.
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
2. **Login if the TC needs auth** (anything beyond the very first TC, or any TC referencing protected pages). Record the `loginAs` helper *once* per spec — reuse it, passing the role each TC needs. Record using the role the login TC specifies (default `ADMIN`).
   1. Snapshot the page (`mcp__playwright__browser_snapshot`).
   2. Find the username field: `role=textbox` with accessible `name` matching `/username|email|user/i`. If multiple textboxes and none match by name, take the first textbox above the password field.
   3. `mcp__playwright__browser_type` the role's username from `.env` (`<ROLE>_USERNAME`). Use it only to drive the browser during recording — do **not** write it into the emitted spec; the spec references `user` from `credsFor(role)` (backed by `process.env`).
   4. Snapshot, find the password field: `role=textbox` with `name=/password/i` (or a textbox whose `type=password` attribute is exposed in the snapshot).
   5. `mcp__playwright__browser_type` the role's password from `.env` (`<ROLE>_PASSWORD`) — again, drive-only; the spec references `password` from `credsFor(role)`, never the literal value.
   6. Snapshot, find the submit button: `role=button` with `name=/sign in|log in|submit/i`.
   7. `mcp__playwright__browser_click` it.
   8. `mcp__playwright__browser_wait_for` until network is idle or a known logged-in element appears.
   9. Record each resolved locator into the `loginAs` helper (the role is a parameter — record the locators once, not per role).
3. **For each subsequent plan step**, in plan order, apply the prefix → MCP mapping below. After resolving a locator, **call the corresponding MCP action to verify it actually works** before emitting the line into the spec — if MCP click/type fails, fall through to the next selector strategy.
4. After the last step of the TC, call `mcp__playwright__browser_close` to reset state, then start the next TC.

### Prefix → MCP action + emitted spec line

| Plan prefix | MCP recording step | Emitted spec line |
|---|---|---|
| `NAVIGATE <url>` | `_navigate` to `<url>` | `await page.goto('<path>');` — emit the **path only** (relative to `baseURL`, e.g. `/app/service-requests`) so `TEST_ENV` re-points it; keep a full literal URL only for genuinely external sites |
| `SNAPSHOT — <desc>` | none (Playwright auto-waits at runtime) | `// SNAPSHOT: <desc>` (comment only) |
| `CLICK <hint>` | `_snapshot`, resolve locator per priority list, `_click` to verify | `await page.<resolved-locator>.click();` |
| `TYPE <field> with \`<value>\`` | `_snapshot`, resolve label/placeholder/textbox locator, `_type` with `<value>` to verify | `await page.<resolved-locator>.fill('<value>');` |
| `SELECT <dropdown> — choose <option>` | `_snapshot`, resolve trigger, `_click`, `_snapshot` menu, resolve option, `_click` | Two lines: trigger click then option click |
| `WAIT for <condition>` | none (observable from later steps) | `await expect(page.<resolved-locator>).toBeVisible();` if condition names a visible element, else `await page.waitForLoadState('networkidle');` |
| `ASSERT <claim>` | `_snapshot`, resolve, observe value | `await expect(page.<resolved-locator>).<matcher>;` |
| `ASSERT (BLOCKING) <claim>` | same as ASSERT, but emit `// ASSERT (BLOCKING): <claim>` above the expect line | same as ASSERT |
| `API <method> <url>` | none — emitted as a network call | `await page.request.<method>('<url>');` |
| `EXTRACT <thing>` | `_snapshot`, resolve, capture text | `const <var> = await page.<resolved-locator>.textContent();` |

**Credential values are never literals.** Login username/password fields are handled by the `loginAs(page, role)` helper — don't emit per-field `.fill()` lines for them in each TC; just call `loginAs`. If a step types a credential outside the standard login (rare), reference `credsFor('<ROLE>').user` / `.password` — never `.fill('<the real value>')`. Any field carrying a secret (token, API key) must likewise reference a `process.env.*` value, not a literal. Only non-secret values (search terms, form data) are emitted as literals.

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

// Environment & credentials come from process.env, loaded from a gitignored .env by
// playwright.config.ts (real env vars / CI secrets always win). NEVER hardcode a
// username, password, or token here — this file is committed and synced to the hub.
//   Site  : baseURL is resolved in playwright.config.ts from TEST_ENV + <ENV>_APP_URL
//           (e.g. TEST_ENV=qa → QA_APP_URL), or a plain APP_URL. Use RELATIVE paths below.
//   Creds : per role, .env defines <ROLE>_USERNAME / <ROLE>_PASSWORD (e.g. ADMIN_USERNAME).

function credsFor(role: string) {
  const key = role.toUpperCase();
  const user = process.env[`${key}_USERNAME`];
  const password = process.env[`${key}_PASSWORD`];
  if (!user || !password) {
    throw new Error(
      `Missing credentials for role "${role}". Set ${key}_USERNAME and ${key}_PASSWORD ` +
      `in .env (copy .env.example) or as CI secrets — see CLAUDE.md → Credentials.`
    );
  }
  return { user, password };
}

// Log in as any role defined in .env. Defaults to ADMIN.
async function loginAs(page: Page, role: string = 'ADMIN') {
  const { user, password } = credsFor(role);
  await page.goto('/');
  // STEP login.1: <verbatim>
  await page.<recorded-locator-for-username>.fill(user);
  // STEP login.2: <verbatim>
  await page.<recorded-locator-for-password>.fill(password);
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
    await loginAs(page);              // or loginAs(page, 'MANAGER') for a different role
    // ... recorded steps ...
  });
});
```

### Hard rules for the spec

- **No secrets in the committed spec.** The site URL comes from `baseURL` (resolved from `TEST_ENV` / `<ENV>_APP_URL` in the gitignored `.env`) and credentials from `credsFor(role)` (`<ROLE>_USERNAME` / `<ROLE>_PASSWORD`, also from `.env`). Never emit a real username, password, token, or API key as a literal anywhere in the file. The `.spec.ts` is committed and synced to the hub — treat it as public.
- Every action line MUST have a `// STEP N: <verbatim plan step>` comment immediately above it. AI-repair uses these as anchors when it has to patch a line.
- Use `getByRole` / `getByLabel` / `getByText` first; raw CSS only as the last-resort fallback with a `// FRAGILE:` comment above it.
- The `loginAs(page, role)` helper at the top is recorded once per spec and reused — do not re-record per TC or per role. Pass the role name each TC needs; it resolves creds from `.env` via `credsFor`.
- Save to `test-plans/<folder>/<kebab-title>.spec.ts`. If the file exists, ask before overwriting (same prompt as the `.md`).

## Finishing reply

One line, nothing else:

> Created `test-plans/<folder>/<name>.md` + `<name>.spec.ts` with **<N> recorded selectors, <K> fallback TODO markers**. Run with `/RunTest <name>`. (If K>0, expect AI-repair to resolve those K lines on first run.)
