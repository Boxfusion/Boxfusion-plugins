# Existing skills to use during diagnosis

Use these in **read/analyse mode only** during diagnosis. A skill's fix or apply mode is only for after "Let's begin!". The exception is Phase 0 test coverage.

## Phase 0: test coverage (starts first, runs alongside Phases 1–2)

`create-integration-tests` and `run-integration-tests` below mean the copy from `shesha-utils` (preferred, installed below), or the `shesha-developer-<version>` plugin matching the system.

| Step | Skill | Use it for | Mode |
|---|---|---|---|
| Back-end inventory | `create-integration-tests`, **Step 0 only** | Mapping source projects to test projects (covered or uncovered); which entities and services have tests | Read only |
| Back-end run | `run-integration-tests` | Building and running the existing tests against a disposable test database (never the QA copy) | Runs tests only |
| Bring the back end to standard | `create-integration-tests`, full workflow | Scaffolding missing test projects and generating entity and service tests | **Automatic** (company standard), on branch `tlc/test-coverage`; tell the user what is added |
| E2E inventory and set-up | The `shesha-auto-testing` chain: `/test-setup` → `/CreateTest` → `/RunTest` (markdown plans with a Playwright spec beside each) | Detecting the harness; setting it up and creating specs for the main journeys of each key role | Automatic, on `tlc/test-coverage` |
| Proof (Phase 3) | the same two harnesses | Reproducing findings as failing tests | Tests only |

**Versions:**
- The test skills are in `shesha-utils` and **shesha-developer-0-43**.
- **shesha-developer-0-46** has no test skills.
- The unversioned **shesha-developer** plugin has only `test-entity-crud-api`.

Where no version fits the system, follow `create-integration-tests`' rules by hand and record this as a gap to raise with the Shesha plugin maintainers. `Shesha.Testing` exists only from 0.46; for 0.43 systems the standalone test infrastructure is the route.

**Known caveats (seen in trial 2; raise with the plugin maintainers, and work around them meanwhile):**
- `run-integration-tests`:
  - it points to backup and restore skills that don't exist;
  - its default backup source reads the main database: point it at the disposable test database explicitly;
  - it has no step to bootstrap an old `.bacpac`: run the host once against the test database, then snapshot;
  - **its generated reset script keeps tables by name prefix, not by schema, so it would wipe workflow definitions and Hangfire tables.** Review the reset script before running it.
- `create-integration-tests` (0.43 standalone template):
  - it references APIs that don't exist in 0.43.37, and registers a service twice;
  - it can silently disable domain event handlers;
  - it doesn't mention that non-virtual service calls need a unit of work, or that in-process dynamic DTOs may have an empty Id;
  - its fixture collection name clashes across projects: make it unique per project;
  - it needs the Enterprise module loaded where the system uses it;
  - `dotnet sln add` bloats the solution: add only the test projects.
- `test-setup` (shesha-auto-testing 1.7.2):
  - it lists `scripts/sync-to-hub.js` but doesn't ship it;
  - it makes Java a hard requirement, only for the Allure 2 HTML report. Treat missing Java as non-blocking (suggested upstream: Allure 3, pure Node, or a soft requirement);
  - it registers the Playwright MCP at **project scope**, so `/CreateTest` must run in a session opened in the target repo (newly installed plugins and MCPs load only in new sessions);
  - it doesn't check private npm feed access: do that first (SKILL.md Phase 0).

**Other tools:** `ilspycmd` (dotnet global tool) decompiles the pinned framework packages from the NuGet cache, to check defaults, anonymous actions and framework behaviour before making claims.

**Where the skills come from:** BoxFusion's own marketplace, `Boxfusion/Boxfusion-plugins` (marketplace name `boxfusion-plugins`). Prefer it over the upstream shesha-io plugins where both exist.
- `shesha-auto-testing`: the e2e chain: `test-setup`, `create-test`, `run-test`, `run-test-remote`, `create-test-from-devops`. `test-setup` scaffolds Playwright, the plans, the dashboard and Allure from bundled templates, and prompts once for the app URL and admin credentials into `.env`.
- `shesha-utils`: `create-integration-tests`, `run-integration-tests`, `add-testcontainer-integration-tests` (useful for CI without a shared database), `harden-permissions`, `clean-form-config` and more.
- `shesha-enterprise`: workflow, document generation, reference numbers.
- App Service and ELMAH log housekeeping (`delete-elmah-logs`, `delete-app-logs`) moved to the infra team's skills in the Azure DevOps repo `Infra-DevOps`, folder `Claude-Skills`. They're not in this marketplace.
- **the security instruments** (the three TLC conducts): `auditing-application-security` (catalogue + probes + probe matrix + disable-list), `hardening-shesha-app` (scan/auto-fix the app-level security settings), `shesha-access-control` (permission + specification design/implement + the authorisation-inventory regression guard). Install alongside the others; if absent, TLC degrades to `harden-permissions` + `security-review` and records the gap.

**If they aren't installed:** check this before the start message (SKILL.md, "Start"). If anything is missing, give the user these commands to run in a terminal, and stop:
```
claude plugin marketplace add Boxfusion/Boxfusion-plugins
claude plugin install shesha-auto-testing@boxfusion-plugins
claude plugin install shesha-utils@boxfusion-plugins
claude plugin install auditing-application-security@boxfusion-plugins
claude plugin install hardening-shesha-app@boxfusion-plugins
claude plugin install shesha-access-control@boxfusion-plugins
```
Then they start a new session, so the skills load. Nothing has run yet, so the new session loses nothing.

**Test plans for BoxFusion systems are published to `Boxfusion/Test-ReportsHub`.** Before creating plans for a system, check `projects/<name>/test-plans/` there for existing ones to reuse.

## During inspection and fixing

| Role | Skill | Use it for | Mode during diagnosis |
|---|---|---|---|
| Forms analyst | `shesha-developer-0-43:clean-form-config` | Dead properties, label-vs-propertyName scripts, missing try/catch, `.then()` chains, layout overflow, JS syntax in embedded code | Report only, no auto-fix |
| Forms analyst | `shesha-developer-0-43:shesha-forms`, `shesha-form-edit` (fetch only) | Fetching live form markup by module and name; knowing the 0.43 versioned form lifecycle | Read only, never push |
| Forms analyst | `shesha-developer-0-43:shesha-design-comprehension` | Comparing what a form is meant to show with what it builds | Read only |
| ORM / Shesha | `shesha-developer-0-43:test-entity-crud-api` | Exercising every entity's CRUD GET endpoint to find broken or over-fetching ones | `--no-fix` |
| ORM / Shesha | `shesha-developer-0-43:shesha-specifications` | Knowing what a proper reusable or global filter looks like, for fix plans | Reference |
| Security | **`auditing-application-security`** | The catalogue + probe engine: full endpoint/entity/form/permission catalogue (JSON + xlsx), the low-privilege and anonymous probes, the **framework-entity CRUD sweep** (SEC-FW), the curated probe matrix (OtpAuditItem reset tokens, the hidden settings endpoints), the admin-takeover procedure (SEC-ESC), `drift.py` for upgrade drift (SEC-DRIFT/RESET/GONE), and the "unused endpoints to disable" list. The Security inspector **runs this for the catalogue and probes**, then adds the cross-area business-flow findings its forms/code/ORM peers hand it (see `auditing-application-security`, business-flow pass). Pass `--package-source` so framework-only callers don't read as unused | Catalogue + probe (read + low-priv probe); never a write-probe |
| Security | **`hardening-shesha-app`** | Scans the app-level security settings — JWT lifetime, sign-out/token-blacklist, failed-login lockout, the Hangfire dashboard filter — and (in `--auto-fix`/Phase 7) applies them with one commit per check | Scan in diagnosis; apply only in `--auto-fix` or after "Let's begin!" |
| Security | `shesha-developer-0-43:harden-permissions` | Listing which endpoints are unprotected (lighter than the full catalogue; use when `auditing-application-security` isn't installed). Services only, no entities; on 0.43.41+ read its version caveats (renamed permissions, records re-applied at start-up) | Audit only, never apply |
| Security | `security-review` | General vulnerability review of code, for hotspots the catalogue flags | Read only |
| Developer | `code-review` | Correctness review of hotspots | Read only |
| Fix phase | **`shesha-access-control`** | The RC-SEC-A remediation: permission naming conventions, `api-permissions-manifest` rows, global-specification patterns, and the **decompile-to-verify-the-real-API discipline** before writing any specification code. Owns the standing **authorisation inventory test**. Its `audit` mode can also feed Phase 2 | `audit` in diagnosis; `design`/`implement` after "Let's begin!" (or inside the `--auto-fix` allowlist for manifest rows + spec scaffolds) |
| Fix phase | **`hardening-shesha-app --apply`** | Applies the scanned settings fixes, one commit per check, with dry-run diffs first. A secret moved out of the repo ships with its hand-over (variable names, set-up, rotation, failure warning) | After "Let's begin!", or auto in `--auto-fix` |
| Fix phase | `upgrade-shesha-stack` | A framework upgrade in the fix plan, **including its step 8 security-drift check** (widened rules, start-up resets, removed endpoints forms still call) | After "Let's begin!" |
| Fix phase | `shesha-app-layer`, `domain-model`, `shesha-fluent-validators`, `shesha-specifications`, `shesha-ref-numbers`, `shesha-notifications`, `shesha-settings`, `shesha-configuration-items`, `shesha-form-edit` (to build form changes for a `.shaconfig` package) | Building the agreed fixes the framework way (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`) | After "Let's begin!" |
| Fix phase | Project e2e skills (e.g. `/CreateTest`, `/RunTest`) | e2e tests before each fix is pushed | After "Let's begin!", and only under `--deep`/`--e2e` (e2e is opt-in) |

**The three security skills are the security instruments TLC conducts.** They live in `Boxfusion/Boxfusion-plugins` and must be installed for the Security and DevOps inspectors and the fix phase to invoke them; if they are not installed, fall back to `harden-permissions` + `security-review` + hand-rolled specifications and record the gap. What each adds over hand-rolling: `auditing-application-security` = the reusable catalogue + curated probe matrix (TLC's security inspector otherwise reinvents a thin subset); `hardening-shesha-app` = automated settings fixes; `shesha-access-control` = the access-control implementation patterns and the regression guard. Their reverse debt — what TLC gives back so they stay strong standalone (the business-flow pass, the POPIA/data-classification layer, proof-by-failing-test, the data-hygiene rules) — is tracked for separate PRs, not changed here.

## Phase 7b: post-merge re-test and re-audit

Runs on the merged branch, on an isolated copy, before human testing (SKILL.md Phase 7b). Re-run only; author nothing new.

| Step | Skill | Use it for | Mode |
|---|---|---|---|
| Existing back-end tests | `run-integration-tests` (and the solution's unit tests) | Pass/fail per suite, before vs after the merge | Runs tests only |
| Existing e2e and regression suites | `shesha-auto-testing:run-test` | Re-running the plans that already exist. **No `/CreateTest` here:** a missing suite is reported as a gap | Runs tests only |
| Existing probe suites | the probe scripts the fixes added | Re-running them on the merged build | Read + probe |
| Security re-audit | `auditing-application-security` | Full run with the low-privilege account and the framework-entity sweep; the admin-takeover probe per role; `drift.py` first start vs restart (and old vs new build if an upgrade merged) | Read + probe; state-changing probes only on the restorable copy |

## Slots for skills still to be added

This draft expects more skills to plug in. When adding one, record:
- the role that uses it;
- what it detects;
- its read-only mode;
- the check file it serves.

- _(slot)_ SQL: query plan / Query Store analysis.
- _(slot)_ DevOps: pipeline and deployment inspection.
- _(slot)_ Mobile app inspection.
- _(slot)_ Integration inspection (USSD, telephony, SMS gateways).
