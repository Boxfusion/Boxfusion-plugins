---
name: test-setup
description: Self-reliant, fast bootstrap for the hybrid Markdown + Playwright testing workflow. One command — `/test-setup` — gets a fresh project to a state where `/CreateTest` works first try. Scaffolds every file the workflow needs (CLAUDE.md, package.json, playwright.config.ts, tsconfig.json, .gitignore, scripts/run-plan.js, scripts/build-dashboard.js, scripts/generate-allure-results.js, scripts/sync-to-hub.js, scripts/hub.config.example.json, test-plans/RULES.md, empty test-plans/ and test-reports/ folders) directly from templates bundled inside this skill — does NOT copy from any other project. Prompts the user once for project-specific values (project slug, app name, app URL, environment, admin credentials), substitutes them into the scaffolded files, then verifies prerequisites (Node ≥ 18, npm install, Playwright Chromium, Java for Allure) and offers to install what's missing. Does NOT configure the Test-Reports-Hub or CI — those are handled by `/submit-test-results` and `/Run-test-remote` respectively when first used. Trigger phrases include "set up testing", "set up the test environment", "install test prerequisites", "check test setup", "prepare to run tests", "bootstrap testing", "scaffold testing", "initialise testing", "test-setup".
---

# Test Setup

One-command bootstrap. After it finishes, `/CreateTest` works immediately — no extra setup steps. Hub publishing and CI dispatch are configured later, by their own skills, when first used.

The skill never copies from a reference project. Every scaffold file lives in `.claude/skills/test-setup/assets/`; the skill reads from there, substitutes user-supplied values, and writes into the project.

## Two Phases

1. **Phase A — Scaffold.** Audit which files are missing. Prompt once for project-specific values. Read each missing template from `assets/`, substitute placeholders, write to the project. Never overwrite existing files without explicit confirmation.
2. **Phase B — Install & verify.** Node ≥ 18 (hard), `npm install`, Playwright Chromium, Java runtime for Allure (hard), then smoke-test the runner.

Run phases sequentially. Within Phase A, ask for values once, then write every file in parallel.

At the end, print the summary defined under **Finishing reply**.

---

## Phase A — Scaffold

### A0. Audit what's present

Check each path relative to the repo root. Build the **missing** list — don't touch present files yet.

| Path | Asset (under `.claude/skills/test-setup/assets/`) | Placeholders |
|---|---|---|
| `CLAUDE.md` | `CLAUDE.md.template` | `__APP_NAME__`, `__APP_URL__`, `__ENV__`, `__ADMIN_USERNAME__`, `__ADMIN_PASSWORD__`, `__PROJECT_NAME__` |
| `package.json` | `package.json.template` | `__PROJECT_NAME__` |
| `playwright.config.ts` | `playwright.config.ts` | `__APP_URL__` |
| `tsconfig.json` | `tsconfig.json` | — |
| `.gitignore` (must contain test entries) | `gitignore.snippet` | — |
| `scripts/run-plan.js` | `scripts/run-plan.js` | — |
| `scripts/build-dashboard.js` | `scripts/build-dashboard.js` | `__APP_NAME__`, `__ENV__` |
| `scripts/generate-allure-results.js` | `scripts/generate-allure-results.js` | `__APP_NAME__`, `__APP_URL__` |
| `scripts/sync-to-hub.js` | `scripts/sync-to-hub.js` | `__PROJECT_NAME__` |
| `scripts/hub.config.example.json` | `scripts/hub.config.example.json` | — |
| `test-plans/RULES.md` | `test-plans/RULES.md` | — |
| `test-plans/` directory | (create if absent) | — |
| `test-reports/` directory | (create if absent) | — |

Print a one-line audit so the user sees what's about to happen:

> Scaffold audit: present=`<count>`, missing=`<list>`. Will prompt for values, then write the missing files.

### A1. Collect values *(one or two prompts max — keep it quick)*

If **every** placeholder-bearing file is already present (CLAUDE.md + package.json + playwright.config.ts + build-dashboard.js + generate-allure-results.js + sync-to-hub.js), skip this step — there's nothing to substitute.

Otherwise:

**Prompt 1** — single `AskUserQuestion` call with these four questions:

1. **Project slug** (header `"Project slug"`) — kebab-case used in package.json and the hub project folder. Derive 2–3 sensible defaults from the repo folder name (e.g. cwd `c:\Projects\Acme-Portal` → `acme-portal`, `acme`, `acmeportal`).
2. **App name** (header `"App name"`) — human-readable. Suggest title-cased slug + " Admin Portal", " Web App", or just title-cased slug.
3. **App URL** (header `"App URL"`) — provide one placeholder option; user picks "Other" to type it.
4. **Environment** (header `"Environment"`) — options: `QA`, `Dev`, `Staging`, `Production`.

**Prompt 2** — second `AskUserQuestion` call for admin credentials. These are separate so the user explicitly opts into providing them:

1. **Admin username** (header `"Admin username"`) — defaults: `admin`, the slug, "Other".
2. **Admin password** (header `"Admin password"`) — options: `"Type a password (Other)"`, `"Skip — I'll fill it in CLAUDE.md myself"` *(writes `<TODO: fill in>`; `/CreateTest` will refuse to run until it's set)*, `"Use placeholder (CHANGE-ME)"` *(writes `CHANGE-ME`, warned in the summary)*.

**Never** invent or echo back real credential values. Capture-only.

If `CLAUDE.md` is **present** and would otherwise need rescaffolding, ask once:

> `CLAUDE.md` already exists. Overwrite it with the templated version? This replaces your current `## Application Under Test` and `## Credentials` sections.

Default **No**. If declined, leave CLAUDE.md alone and print the snippet in A4 so the user can paste it manually.

### A2. Substitute and write

For every file in **Missing**, in parallel:

1. `Read` the corresponding asset from `.claude/skills/test-setup/assets/`.
2. Replace each `__PLACEHOLDER__` with the captured value.
3. `Write` to the target path.

For directories (`test-plans/`, `test-reports/`): create them with a `.gitkeep` so they survive a fresh git clone.

For `.gitignore`: if the file exists and lacks the test entries (look for `node_modules/` + `allure-results/` + `playwright-report/`), append `gitignore.snippet`. If `.gitignore` doesn't exist, write the snippet as the whole file.

### A3. Verify substitution

```
Grep "__[A-Z_]+__" across CLAUDE.md, package.json, playwright.config.ts, scripts/
```

Any hit means a placeholder leaked. Stop and tell the user which file + which placeholder; do not proceed to Phase B.

### A4. If CLAUDE.md was kept, print the snippet for manual paste

When the user declined to overwrite an existing `CLAUDE.md`, print the substituted sections they need to add:

```
## Application Under Test
| Key | Value |
|-----|-------|
| App | <APP_NAME> |
| URL | <APP_URL> |
| Environment | <ENV> |

## Credentials
| Role | Username | Password |
|------|----------|----------|
| Admin | <USERNAME> | <PASSWORD> |
```

Tell them: *"`/CreateTest` reads these sections at authoring time. Paste them into `CLAUDE.md` before invoking it."*

---

## Phase B — Install & verify

Run these **sequentially**.

### B1. Node ≥ 18 *(hard requirement)*

```bash
node --version
```

- **Healthy**: `v18.x` or higher.
- **Hard missing**: stop and tell the user:
  > Node 18 or newer is required. Install from https://nodejs.org/ (LTS), restart this shell, then re-run `/test-setup`.

### B2. npm dependencies *(soft missing — installable)*

```bash
test -d node_modules/@playwright/test && test -d node_modules/allure-commandline && echo OK
```

- **Healthy**: `OK`.
- **Soft missing**: ask once `Install npm dependencies now? (npm install)`. On yes, run `npm install`. On no, mark skipped and continue — Phase B3/B4/B5 will fail loudly.

### B3. Playwright Chromium *(soft missing)*

```bash
npx playwright install --dry-run chromium 2>&1
```

If the output contains `is already installed`, the browser is present. Otherwise ask once, then run `npx playwright install chromium`.

### B4. Java runtime for Allure CLI *(hard requirement)*

```bash
java -version
```

- **Healthy**: a version string was printed (Java prints to stderr but exits 0).
- **Hard missing**: stop and tell the user:
  > Allure CLI needs a Java runtime (JRE 11 or newer). Install one of:
  > - Eclipse Temurin: https://adoptium.net/temurin/releases/
  > - Microsoft OpenJDK: https://learn.microsoft.com/java/openjdk/download
  >
  > After install, open a new shell so `java` is on PATH, then re-run `/test-setup`.

Do **not** attempt to install Java via `winget`, `choco`, or any other package manager.

### B5. Playwright MCP server *(soft missing — required for `/CreateTest`)*

`/CreateTest` records selectors live by driving a browser through the Playwright MCP server. The server must be registered with Claude Code before any plan can be authored.

Check whether it's already registered:

```bash
claude mcp list 2>&1
```

Look for a line beginning with `playwright`. If present, mark this step ✓ and move on.

If absent, ask once:

> Register the Playwright MCP server now? Runs `claude mcp add playwright -- npx -y @playwright/mcp@latest`. Required for `/CreateTest`.

On yes, run:

```bash
claude mcp add playwright -- npx -y @playwright/mcp@latest
```

Then re-run `claude mcp list` to confirm `playwright` is now listed. If the add command failed, surface the stderr verbatim — common causes are `claude` CLI not on PATH or a stale lockfile in `~/.claude/`. Do not retry silently.

On no, mark this step skipped and warn the user in the finishing summary that `/CreateTest` will fail until they register the server.

### B6. Smoke-test the runner

```bash
node scripts/run-plan.js --help 2>&1 | head -20
```

- **Healthy**: the runner prints usage or exits cleanly on the missing argument.
- **Failed**: surface the error verbatim. Usually means B2 was skipped or `npm install` partially failed — re-run it.

---

## Finishing reply

Pick the line that matches what actually happened. Do **not** claim "complete" if any hard step failed.

If Phase A scaffolded files and Phase B passed:

> **Setup complete.** Scaffolded `<n>` file(s). Prerequisites verified (Node ✓, deps ✓, Chromium ✓, Java ✓, runner ✓).
> Next: `/CreateTest` to author a test.

If Phase A found nothing missing and Phase B passed:

> **Setup verified — nothing scaffolded.** Prerequisites ✓. Ready for `/CreateTest`.

If something blocking failed:

> **Setup blocked at Phase <A|B>, step <ID>: <name>.** <one-line reason>. <one-line next action>. Re-run `/test-setup` once it's resolved.

If the user picked the `CHANGE-ME` password placeholder in A1:

> ⚠️ The Admin password in `CLAUDE.md` is `CHANGE-ME`. Edit it before running `/CreateTest`.

If the user picked Skip on the admin password:

> ⚠️ The Admin password in `CLAUDE.md` is `<TODO: fill in>`. Replace it before running `/CreateTest`.

**Do not** mention hub config or CI prereqs in the summary. Those are configured separately by `/submit-test-results` and `/Run-test-remote` when first invoked.

---

## Idempotence guarantees

- **Never overwrite a present file** without explicit user confirmation.
- **Never write real credentials** that weren't typed by the user in this session.
- **Re-running on a healthy project** produces *"Setup verified — nothing scaffolded"* and exits in seconds.
- **Re-running after a partial setup** picks up only the missing files.
