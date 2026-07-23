---
name: run-test-remote
description: Dispatch a test plan to GitHub Actions instead of running it locally — the cloud-side workflow uses claude-code-action to drive the test, posts a Teams Adaptive Card on failure, and publishes an Allure report to gh-pages. Trigger phrases include "/Run-test-remote", "run test remote", "run on CI", "dispatch test on github actions", "run remote test", "trigger e2e workflow", "kick off the workflow". If `.github/workflows/e2e-test.yml` is missing the skill scaffolds it from a template and walks the user through wiring the required secrets (`ANTHROPIC_API_KEY`, a `<ROLE>_PASSWORD` per login role such as `ADMIN_PASSWORD`, optional `TEAMS_WEBHOOK_URL`) plus the non-secret repo variables (`TEST_ENV`, `<ENV>_APP_URL`, `<ROLE>_USERNAME`). If present, the skill picks plan(s) via the same disambiguation UX as `/RunTest`, dispatches each via `gh workflow run e2e-test.yml -f test_plan=<path>`, and prints the resulting run URL. Optional `--watch` flag blocks until the run completes.
---

# Run Test Remote

Dispatch the test plan to GitHub Actions and print the run URL. The cloud workflow does the actual execution — this skill is the local control surface.

## Pre-flight (mandatory, in order)

1. **Detect the workflow file.**
   ```bash
   test -f .github/workflows/e2e-test.yml && echo HAS_WORKFLOW || echo NO_WORKFLOW
   ```
   - `HAS_WORKFLOW`: continue.
   - `NO_WORKFLOW`: jump to the **Scaffolding flow** below.

2. **Detect `gh` CLI.**
   ```bash
   gh --version
   ```
   Missing → stop with:
   > GitHub CLI not installed. Install from https://cli.github.com/, then `gh auth login`, then re-run `/Run-test-remote`.

3. **Detect `gh` auth.**
   ```bash
   gh auth status
   ```
   Not authenticated → stop with:
   > GitHub CLI is not authenticated. Run `gh auth login` (pick GitHub.com, HTTPS, login via browser), then re-run `/Run-test-remote`.

4. **Check required secrets.**
   ```bash
   gh secret list
   ```
   Required secrets: `ANTHROPIC_API_KEY`, plus one **`<ROLE>_PASSWORD`** per login role the test uses — at minimum `ADMIN_PASSWORD` (the same env-var names the specs read from `process.env`; see `CLAUDE.md` → Credentials). Optional secret: `TEAMS_WEBHOOK_URL` (skip notification if absent).

   Non-secret config the workflow also needs (set as **repo Variables** — `gh variable set` — or hardcode in the workflow's `env:`): `TEST_ENV`, the active `<ENV>_APP_URL` (e.g. `QA_APP_URL`), and one `<ROLE>_USERNAME` per role. These aren't secrets, so keep them out of `gh secret`.

   If a *required* secret is missing, stop with the exact commands the user needs:
   > Missing secret(s): `<list>`. Set them and re-run:
   > ```
   > gh secret set ANTHROPIC_API_KEY
   > gh secret set ADMIN_PASSWORD          # + one <ROLE>_PASSWORD per additional role
   > ```
   > Non-secret config (repo variables):
   > ```
   > gh variable set TEST_ENV --body qa
   > gh variable set QA_APP_URL --body https://qa.example.com
   > gh variable set ADMIN_USERNAME --body admin
   > ```
   > `TEAMS_WEBHOOK_URL` is optional — set it if you want Teams notifications on failure:
   > ```
   > gh secret set TEAMS_WEBHOOK_URL
   > ```

   If `gh secret list` errors (insufficient scope), note `secret check skipped — gh scope missing` and proceed. The user can still dispatch; the workflow will fail loudly if a secret is actually absent.

## Scaffolding flow (workflow file missing)

Generate `.github/workflows/e2e-test.yml` from the template embedded in this skill. The template is the **current `e2e-test.yml`** in the repo after the recent updates (nightly-skip, Teams notification, basename fix). To stay consistent, copy the file as-is from the repo's existing workflow rather than re-typing it — the canonical version lives at [.github/workflows/e2e-test.yml](../../.github/workflows/e2e-test.yml).

If for some reason the file is missing entirely from the repo, regenerate it from this skill's `template/e2e-test.yml` companion (if present) or instruct the user to pull from main.

After writing the file:

> Scaffolded `.github/workflows/e2e-test.yml`. Required secrets:
> - `ANTHROPIC_API_KEY` — `gh secret set ANTHROPIC_API_KEY`
> - `ADMIN_PASSWORD` (and one `<ROLE>_PASSWORD` per additional login role) — `gh secret set ADMIN_PASSWORD`
> - `TEAMS_WEBHOOK_URL` (optional, for failure notifications) — `gh secret set TEAMS_WEBHOOK_URL`
>
> Non-secret config as repo variables:
> - `gh variable set TEST_ENV --body qa`
> - `gh variable set QA_APP_URL --body <url>` (the active `<ENV>_APP_URL`)
> - `gh variable set ADMIN_USERNAME --body admin` (one `<ROLE>_USERNAME` per role)
>
> The workflow must pass these through as `env:` to the test step so the specs read them from `process.env`. Configure them, commit + push the workflow file, then re-run `/Run-test-remote`.

Stop here. The user must commit and push the workflow before GitHub Actions can see it.

## Pick plan(s) — same disambiguation UX as /RunTest

Use the same resolution order and list format that `run-test` uses:

1. Explicit path → confirm + proceed.
2. Single-match filename hint → confirm + proceed.
3. Zero matches → present the full plan list and ask.
4. Multiple matches → present matching subset and ask.
5. `"all"` → run every plan (dispatched as a separate workflow run each).

List format (include last-run status from the most recent local report):

```
Multiple plans match (or none specified). Pick one or more (comma-separated, ranges, or "all"):

  1. calls/create-call-log              [last: PASSED 2026-05-20]
  2. cases/create-call-log-entry        [last: PARTIAL 2026-05-19]
  3. cases/create-case                  [last: PASSED 2026-05-20]
  4. service-requests/create-service-request       [last: —]
  5. service-requests/create-service-request-v2    [last: FAILED 2026-05-18]
```

Parse `1,3,5` / `1-3` / `all`. Confirm:

> Resolved to: `cases/create-case.md`, `service-requests/create-service-request-v2.md` — dispatching each as a separate workflow run.

## Dispatch

For each selected plan, run:

```bash
gh workflow run e2e-test.yml -f test_plan=<relative-path>
```

The workflow's `inputs.test_plan` is the path **relative to `test-plans/`**, so strip that prefix (e.g. `test-plans/cases/create-case.md` → `cases/create-case.md`).

Immediately after dispatch, grab the resulting run:

```bash
gh run list --workflow=e2e-test.yml --limit 1 --json databaseId,url,createdAt
```

Take the first row (most recent). Sometimes GitHub takes a couple of seconds to register the dispatch — if the most recent run has a `createdAt` older than 30 seconds ago, sleep 2s and re-list once.

## Optional `--watch` flag

If the user passes `--watch`:

```bash
gh run watch <runId> --exit-status
```

This blocks until the run finishes and exits with the run's status code. Use it when the user wants a synchronous "wait for green" workflow.

Default (no `--watch`): non-blocking — just print the URL and exit.

## Finishing reply

### Non-blocking (default)

> Dispatched `<plan>` to GitHub Actions: https://github.com/<owner>/<repo>/actions/runs/<id>
>
> The workflow will:
> - Run the plan via `claude-code-action`
> - Deploy Allure to `gh-pages/runs/<id>/`
> - Post a summary to the run page
> - Post a Teams card to `TEAMS_WEBHOOK_URL` if the run fails (skipped silently if the secret isn't set)

If multiple plans were dispatched, list each on its own line.

### `--watch` mode

> Workflow run <id>: **<status>** (<duration>).
> - Run page: https://github.com/<owner>/<repo>/actions/runs/<id>
> - Allure report: https://<owner>.github.io/<repo>/runs/<id>/

If the run failed and Teams is configured, append:
> Teams card delivered to your configured webhook.
