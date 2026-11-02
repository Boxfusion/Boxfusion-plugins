---
name: boxfusion-tlc
description: DRAFT. Diagnose and fix a BoxFusion Shesha / ABP system end to end, the "TLC" review. It brings test coverage up to company standard first. Then a specialist team inspects code, SQL, the ORM, forms, security, operations and App Insights, proves each finding with a test, and writes a plain-English, no-blame report with BA questions, PM concerns and a separate Shesha team report. The user agrees or discusses each finding; on "Let's begin!" fixes ship the Shesha way under one {SystemName}-TLC-Fixes work item, as PRs. Use when asked to diagnose, audit, health-check, review or "TLC" a whole system, or to find what's wrong with it.
argument-hint: "[--educational | --interactive | --auto-fix] [--quick | --deep] [--area code|sql|orm|security|ops|forms]"
---

# BoxFusion TLC: system diagnosis and fixes

> **Status: DRAFT.** It is trialled on real projects and refined. More existing skills will be plugged into the investigation slots (see `references/skills-to-use.md`). Trial lessons: `TRIAL-NOTES.md`.

This skill turns "the system keeps having problems" into a proven, ranked, plain-English list of what is wrong, why it matters, and what to do about it. Once the user agrees, it fixes the problems the framework's way.

Many BoxFusion systems were built by developers early in their careers. The report is therefore also a **teaching document**:
- every finding explains why the pattern is harmful and what good looks like, in plain English;
- it uses the system's own code as the example;
- it never names or blames people.

## Who it talks to

**Only the person who started it.** Everyone else receives documents through them.

| Step | What the user sees |
|---|---|
| Start | One setup message asking only for what can't be detected (see "Start" below) |
| Phase 0 | A note of what test coverage existed and what was added. No question: coverage is company standard |
| Phases 1–5 | One-line progress updates, then the finished report. Nothing else (see below) |
| Urgent stop (only if needed) | A short alert when a critical exposure is live now, e.g. an anonymous endpoint returning secrets |
| Escalation (only if needed) | When a QA finding is serious and likely present in production, a request to escalate to the IT Manager for production data |
| Phase 6 | Each finding in turn, with two options: **Agree** or **Discuss** |
| End | The agreed plan, the proposed board (one parent work item and a few tasks) and the PR grouping, then **"Let's begin!"** |

**Documents for other people,** handed to the user to pass on:
- **The report** for the PM (summary, concerns), the BA (questions) and the developers (teaching sections).
- **A note to pass it on:** the summary ends with *"Please pass this on to the previous developer(s) of this system, if applicable."* The skill never tries to identify who wrote what.
- **The Shesha team report** (`${CLAUDE_PLUGIN_ROOT}/shared/templates/shesha-team-report.md`), for framework defects only. It has everything they need to act, a ready-to-paste Claude prompt, and copy-paste SR wording where an SR should be logged.

### What the user sees during a run

A run is quiet. The user sees only:
- **one-line progress updates**, e.g. "Inspection 6/8 done", "Fact-check: 2 corrections", "Proof: 9/14 reproduced";
- **the finished report**, as a short summary with the file path;
- **then the walkthrough.**

Rules:
- Inspector, fact-checker, tester and consolidation hand-backs go **straight into their files** (`diagnosis/findings/<area>.md`, `REPORT.md`). Never echo them, or summaries of them, into the chat.
- No tool noise, no interim finding lists, no "here is what the Security inspector found".
- **The one exception is an urgent stop:** a critical exposure that is live now (e.g. the settings probe in `checks/security.md` SEC-I returns a secret anonymously). Give a short alert: what is exposed, where, the evidence level, and the one action to take now (usually "tell the IT Manager"). Then carry on quietly.
- Questions to the user are still asked when something truly blocks progress (an expired feed token, production escalation).

## Ground rules (always)

1. **Diagnose first, change nothing, with one exception for tests.**
   - During diagnosis, never modify the application, its forms or its configuration.
   - Skills that can write (e.g. `harden-permissions`, `shesha-form-edit`, `clean-form-config` auto-fix) are used in read/analyse mode only.
   - **Test coverage is the exception — in the modes that write.** In `--interactive`/`--auto-fix` Phase 0 adds missing integration tests and (under `--deep`/`--e2e`) the e2e harness without asking, on a branch; it never changes application code to do so. In `--educational` and `--static` (and any read-only/propose-only or no-DB-copy run) Phase 0 **only inventories coverage and reports the gap** — it writes nothing and creates no branch. Pick the degraded behaviour whenever the invocation is read-only; don't guess.
   - Fixing starts only after every finding is agreed and the user says **"Let's begin!"**
2. **Framework first.** See `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`. These are Shesha / ABP systems, so every fix uses the framework's native mechanism:
   - forms, reference lists, settings, permissions and entity configuration ship in **`.shaconfig` packages**;
   - row-level rules are **specifications**;
   - validation uses **Fluent validators**;
   - side effects run on **after-commit events**;
   - and so on.

   No custom JavaScript, raw SQL scripts or hand-made database edits where the framework provides a way. Shortcuts only in a genuine emergency, recorded as such with a follow-up to do it properly. The same standard applies when judging the existing system: bypassing the framework is a finding.
3. **Data safety first:** see `${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`.
   - Work on a local copy of the **QA** database.
   - Escalate for **production** data only when a QA finding is serious enough, and likely enough to exist in production, that proving it there matters. The user asks the IT Manager, who may grant access or hand the work to senior staff.
   - Personal data never leaves the machine. Reports carry counts, not people.
4. **Proof before ranking.** Every finding carries an evidence level:
   - `REPRODUCED`: shown to happen, preferably by a named test that fails today.
   - `CONFIRMED-IN-LOGS`: production telemetry shows it happening.
   - `VERIFIED-ARTEFACT`: a checked fact about a file or configuration (a secret in a file, a scanner hit, a compile failure, measured config drift). Scanner and compile results are this level, not `REPRODUCED`.
   - `CODE-ONLY`: visible in code or configuration, not yet shown to happen.
   - `DATA-ANOMALY`: odd data with no proven cause yet. It may just be poor data.

   Only the first three count as proven. Chase every anomaly until it is explained or reproduced. **An unproven critical finding is worded "the configuration allows…" or "the code allows…"** in the summary and the finding title, until it is reproduced.
5. **Severity is not sequence.** Severity says how bad something is; the fix sequence says what has to happen first. Never rank a finding higher only so it lands first in the plan. A process gap can be medium and still be step one.
6. **No blame.** Findings describe what the system does, never who did it. Where history helps, cite a **date and a PR or commit link**, nothing more. Cite the link only: never look up or record authors (no `git blame` for names).
7. **Plain English.** Write for a PM, a BA and a first-year developer at the same time. Technical detail goes in the evidence appendix.
8. **Discretion over dogma.** A "best practice" that hurts this system is not a finding. For example, full request logging (e.g. ELMAH) that kills API performance or fills the disk is not a fix. Weigh cost against benefit and say so.

## Start (before any phase)

Keep it to one message, and detect before asking.
1. **Check the plugins** the run needs (`references/skills-to-use.md`, "If they aren't installed"). If any are missing, give the install commands and stop. Nothing has run yet, so a new session loses nothing.
2. **Detect:**
   - the repo: the working directory;
   - test logins: from test plans, seed files or `.env`;
   - App Insights: from appsettings or the connection string;
   - the Shesha version: from the packages.
3. **Ask once, only for what is still missing:**
   - a local copy of the QA database (if there is none, see `${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`, "Which database");
   - any separate front-end, mobile or USSD repos;
   - known pain points;
   - test logins, only if none were found (written only to the gitignored `.env`).
4. **Check the private npm feed** (Phase 0, "Check access early").
5. Launch both teams (Phase 0 and Phases 1–2).

**Outputs.** Decide the output path **before writing anything**, and assert it:
- **Owning the checkout (a normal engagement on your own clone):** run files go in `diagnosis/` at the target repo root; add `diagnosis/` to `.git/info/exclude` and never commit it.
- **Read-only / propose-only against someone else's checkout (HARD RULE):** write **nothing** under the app root — not `diagnosis/`, not the repo root, not anywhere inside it. All output goes to an **external run folder of your own** (e.g. `<your workspace>/runs/<system>/`). Before the first write, assert the resolved output path is outside the app root; if it isn't, stop and fix the path. This is what keeps "`git status` identical before and after" true and prevents the leakage seen in the wild — an app repo root littered with prior runs' `FINDINGS-SUMMARY.md`/`FIX-LIST.md`/`evidence-*.md`. Those are exactly what this rule exists to prevent; if you find such artefacts on arrival, note them as pre-existing (no blame — you can't prove which run made them) and still write your own output externally.
- **A subagent inspector cannot Write a file at all** (the harness blocks report-path writes) — so every inspector/sweeper returns its deliverable as separator-wrapped text (`references/team.md`, "Saving hand-backs") and the **orchestrating session persists it, to the external run folder on a propose-only run**. Never write an inspector brief telling it to save its own file, and never tell it to "write under runs/…": it will fail; the orchestrator owns persistence.

## Phases

| Phase | What happens | Output |
|---|---|---|
| 0. Test coverage | **Starts first and runs in parallel with Phases 1–2,** with its own staff. Isolate the copy; inventory integration and e2e coverage; **add what's missing** (company standard); run a baseline | `diagnosis/00-test-readiness.md` (the test-coverage output) |
| 1. Reconnaissance | Stack, versions, roles/permissions model, deploy history, telemetry, environments. Runs alongside Phase 0 | `diagnosis/01-recon.md` |
| 2. Inspection | Specialists work in parallel, one owner per topic, alongside Phase 0 | One findings file per area |
| 2b. Fact-check | **Mandatory.** Check every critical and high claim against the code and data before merging | Corrections |
| 3. Proof | **The only phase that waits for the Phase 0 harness.** Reproduce findings as failing tests that fail for the right reason; App Insights; escalate for production data only if justified | Evidence levels updated |
| 4. Consolidation | Senior Engineer merges and plans; Architect finds root causes and orders the fixes | Draft report |
| 5. Report | Main report plus the Shesha team report | `diagnosis/REPORT.md`, `diagnosis/SHESHA-TEAM-REPORT.md` |
| 6. Walkthrough | Each finding: **Agree** or **Discuss**. Then the board and PR plan, then **"Let's begin!"** | Agreed plan |
| 7. Fix | Work item `{SystemName}-TLC-Fixes` with consolidated tasks; engineer sessions build the fixes the framework's way, with tests; PRs | PRs linked to tasks |
| 8. Learn | New problem types and skill faults become a generalised, scanned skill-upgrade PR; **reviewer: Igor Kors (igorkors-boxfusion), always** | `diagnosis/LEARNINGS.md`, upgrade PR |

**Timing in one line:** Phase 0 and Phases 1–2 start together and run side by side, with two separate sets of staff (the test-coverage team and the topic owners). Phase 2b follows Phase 2. Only Phase 3 waits for the harness. Phases 4–5 follow Phase 3.

**Target:** a ranked report in about 2 hours, and the whole run well under 5 hours on a modern laptop. Staff both teams fully (`references/team.md`, "Staffing and parallelism"). Phase 0 authoring that is still running is listed in the report as still open, not waited for.

**Run modes.** Three independent axes — autonomy, depth, scope — plus an internal development flag. Phase 0's test-coverage inventory runs in every mode; the e2e harness is opt-in (see depth).

*Autonomy — how much the human gates the run (default `--educational`):*
- `--educational` (default): the full sweep → the consolidated, no-blame teaching report with BA/PM questions and the Shesha-team SR drafts. **Read-only on the application and its config** — it diagnoses and teaches, opens no PRs, and makes no change the user must review. The walkthrough is offered but the report is the deliverable. The safest default and the right one for learning a system. *Phase 0 degrades here: it inventories test coverage and reports the gap as a finding, but does **not** add tests or create the `tlc/test-coverage` branch — that belongs to `--interactive`/`--auto-fix`.*
- `--interactive`: the walkthrough — each finding **Agree** or **Discuss**, then on "Let's begin!" execute the agreed fixes the framework way and open PRs (Phases 6–7). Active remediation with a human gate on every change.
- `--auto-fix` (alias `--headless`): run the sweep and apply the **safe, mechanical** fixes automatically, open their PRs, and report everything else as findings. For CI and bulk hardening across many systems. **Bounded by the allowlist below** — it never auto-applies a judgement-heavy change.

*Depth — how hard it looks:*
- `--quick` (default when no App Insights): static analysis plus the low-privilege and anonymous probes; skips Phase 3's telemetry proof and production escalation.
- `--static`: static analysis only — **no backend is started and no DB is restored**. Every detection that needs a running backend (the SEC-C/SEC-I anonymous and low-privilege probes, OtpAuditItem/`/elmah`/Hangfire/`/graphql` live checks, all `sql/diagnostic-queries.sql` output, OPS-A..E telemetry, live form-version drift) is reported **CODE-ONLY or "not assessed"**, never claimed as observed. This is the safe first-pass / propose-only / no-copy mode. `--quick` with no DB copy available degrades to exactly this.
- `--deep` (default when App Insights access exists): adds telemetry proof and, if justified, production escalation, **and** the e2e harness and specs.
- E2e is the single heaviest step, so it is **opt-in**: it runs only under `--deep`, or when `--e2e` is passed on its own. Back-end integration tests (Phase 0) are not e2e and run whenever the harness builds — but only in `--interactive`/`--auto-fix`; `--educational` and `--static` inventory coverage without building it.
- **Tag per check by evidence source.** Each Detect/Prove bullet draws on one of: **file** (repo read/grep — always available), **decompile** (ilspycmd on a pinned DLL — available static, settles framework facts), **DB** (a restored copy — needs a backend/restore), **App Insights** (telemetry — needs access), **DevOps-API** (pipelines/branch policies — needs the Azure DevOps API). Only **file** and **decompile** run under `--static`; DB/App Insights/DevOps-API detections are marked **"not assessed"**, never "fine". When a bullet's source is ambiguous, name it so the inspector knows whether it can claim the result on this run.

*Scope — how wide (default: everything):*
- `--area <area>`: limit the inspection to one area (`references/team.md`, "ID ranges"). Phase 0, the fact-check and the walkthrough still run for that area's findings.
- `--security-only`: run **only the security division** — see "The `--security-only` mode" below. For rapid, repeatable security sweeps across many systems (the primary mode after a breach), by one person over every project or by a team splitting the projects between them.

**The `--security-only` mode.** A focused, shippable security sweep. It runs the security division and nothing else, to one standard, so two operators on the same repo+environment get the same security findings and the same remediation plan (`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`).
- **In scope:** every `checks/security.md` check (SEC-A…SEC-S — the SEC-A…SEC-O set plus the R14 coverage additions SEC-P JWT-trust, SEC-Q GraphQL data-plane, SEC-R background-job trust, SEC-S tenant isolation), plus the security-relevant checks owned by other areas that the Security reviewer already consumes as handovers — the permission-checker and trusted-header/anonymous-endpoint items in `checks/code.md` (CODE-G-1 inverse permission-checker, CODE-F-1/F-2 server-trusted scope header, CODE-G-3 anonymous test endpoints) and the workflow-in-browser items in `checks/forms.md` (FORM-G, FORM-D) that feed **SEC-K**. SEC-K stays in scope: it is cross-area, so the run still reads the forms/workflow/code it needs to trace a business flow, but only for the security question.
- **Out of scope (say so, don't silently drop):** performance, ORM scale, SQL craftsmanship, ops/telemetry, forms UX, code quality that isn't security-relevant. The report names these as "not in scope for `--security-only` — run a full sweep for these."
- **Phases:** 1 (recon — security-relevant facts + the Capability Manifest), 2 (security inspection; **SEC-I settings probe first**), 2b (fact-check every critical/high), 3 (proof — live probes/tests where the manifest allows), 5 (a security-only report). Phase 0 test-coverage is **inventory-only** here (no harness authoring) unless combined with `--interactive`/`--auto-fix`. Phase 8 (learn) still runs.
- **Combines with the autonomy and depth axes:** `--security-only --educational` (read-only security report — the default and the safe one for a team sweep), `--security-only --interactive` (walk + fix the agreed security findings), `--security-only --auto-fix` (apply only the allowlisted mechanical security fixes — token lifetime, sign-out, lockout, Hangfire, CORS allow-list, security headers, gate anon elmah/swagger/graphql — via `hardening-shesha-app`). Depth (`--static`/`--quick`/`--deep`) controls live probing exactly as elsewhere.
- **Team split (the breach-response use):** several operators each run `--security-only` on different projects, or on one large project split by the Security reviewer's own sub-areas — access-control (SEC-A/B/C/K/P/Q/S + CODE-G-1), secrets & config (SEC-E/I/O/D), input & data (SEC-G/L/M/N/H), real-time & messaging (SEC-F/J/R). Because every finding has a stable id, evidence level, scored severity and templated remediation (`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md`), the per-project or per-sub-area reports merge into one consolidated picture without renumbering or re-ranking.

*Internal:*
- `--dev-mode-only` (formerly `--trial`): this system is a **skill-development subject**. Run Phases 0–5 and 8; present the board **as a proposal** (no work items, fix branches or PRs); no "Let's begin!"; Phase 6 only if asked. Learnings drive skill upgrades. **This flag is scaffolding — remove it once the skill is settled**, not a user-facing mode.

**The `--auto-fix` allowlist (safety boundary).** `--auto-fix` / `--headless` may apply only *mechanical, framework-native, low-risk* fixes: the `hardening-shesha-app` settings (token lifetime, sign-out/blacklist, lockout, Hangfire dashboard), endpoint permission-manifest rows mapped to **existing** permission-definitions, global-specification scaffolds, and removal of dead or clearly test-only endpoints. Everything judgement-heavy — rewriting a workflow, a data-integrity fix, "who may see what", anything that changes business behaviour — **never auto-applies**; it drops to a finding for human review. When in doubt, it is a finding, not a fix. Every auto-applied fix still gets its own commit and its PR, and the report lists exactly what was changed.
Two hard preconditions each auto-fix must check first (both from real repos):
- **A "test-only"/"dead" endpoint is only removable if nothing references it.** Check the front end and DI/service registrations for the type and its route before deleting — an endpoint the admin portal still mounts (e.g. a `SignalRTest` service wired into `app-provider`) will break the build. No cross-reference check ⇒ it stays a finding.
- **Permission-manifest mapping needs existing permission-definitions to map to.** A system with no permission-definitions has nothing safe to map; `--auto-fix` must cleanly **no-op and report**, never invent a permission scheme on its own.

Phase 0's inventory runs in every mode.

### Phase 0: test coverage (starts first, runs alongside the inspection)

Every finding has to be proven by a test that reproduces it, and test coverage is a BoxFusion standard. Phase 0 is mandatory and starts first. **It runs in parallel with Phases 1–2,** which only read. Launch the test-coverage staff and the topic owners together; don't wait for one before starting the other. **Only Phase 3 (proof) waits until the harness is ready.** Staff it as in `references/team.md` → "Staffing and parallelism". Use the framework's own skills, not hand-rolled scaffolding (`references/skills-to-use.md`, Phase 0).

**Check access early, before any install.** In the first minutes:
- **Private npm feeds** (e.g. Azure Artifacts) need a token that expires. Run `npm ping` against the feed and `npm view` of one private package the portal depends on. A 401 or 403 means the token has expired. Tell the user exactly how to refresh it (on Windows: `npx vsts-npm-auth -config .npmrc -F` in the portal folder; otherwise a new personal access token with Packaging (Read) scope in the **user-level** `.npmrc`). Never print the token.
- While waiting for the token, **carry on with what doesn't need the portal:** back-end integration tests and API-level specs. When the UI specs run, label their results with the portal version actually used (e.g. an older build already installed).
- Run `npm ci` in each new worktree. A stale `node_modules` that doesn't match the lock file gives misleading failures, and some commit hooks fail without it.

0. **Isolate and prove the copy** (`${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`, "Before any backend starts"): integrations cut off or stood in, and the canary passed, before any backend start.
1. **Back-end inventory.**
   - Run the Step 0 inventory of `create-integration-tests` (from `shesha-utils`, or the `shesha-developer-<version>` plugin matching the system). If no version of it fits, follow its rules by hand and note the gap.
   - It maps each source project to its test project and lists which entities and app services have tests.
   - Build and run the existing tests with `run-integration-tests` against a disposable test database, never the QA copy.
   - Record pass, fail and skip counts, plus projects that don't compile or aren't in the solution.
2. **E2E inventory.** Look for:
   - `playwright.config.*`, specs and test plans (e.g. the `shesha-auto-testing` plugin's chain `/test-setup` → `/CreateTest` → `/RunTest`, with `test-plans/*.md` and a `.spec.ts` beside each, plus `scripts/run-plan.js`);
   - which user journeys and roles are covered;
   - test logins.
3. **CI.** Does a pipeline build and run the tests on pull requests and publish results (e.g. JUnit XML)?
4. **Bring it up to standard. Don't ask.** On a branch `tlc/test-coverage`:
   - repair broken test projects and add them to the solution;
   - run `create-integration-tests` (its full workflow) for uncovered modules;
   - set up the e2e harness (`/test-setup`) and create plans and specs (`/CreateTest`) for the main journeys of each key role. Author the plans in a **session opened in the target repo**: `test-setup` registers the Playwright MCP at project scope, so a session opened elsewhere can't use it.
   - **Never two writers in one worktree.** Each writer (e2e scaffold, each integration-test engineer) has its own worktree and branch, merged into `tlc/test-coverage` at the end.

   Tell the user what is being added and roughly how long it will take. **No prompts for setup steps.** Coverage is company standard, so these run automatically:
   - dependency installs (`npm install`, the Playwright browsers, NuGet restore);
   - `test-setup`'s verification steps;
   - registering the Playwright MCP server;
   - provisioning a disposable test database.

   When a skill used here (e.g. `test-setup`) would ask "install now?", treat the answer as yes. Test logins come from the Start step.

   Ask the user only for software that needs a system install. A missing Java runtime is **not** a blocker: it only stops the Allure HTML report (Allure 2 CLI). Tests, JUnit XML, the Playwright report and the markdown dashboard all work without it, so carry on and note it.

   Pause only if something truly blocks progress.
5. **Baseline.** Run everything once and record the results. Tests that fail on the untouched system are early findings. Record which existing tests can't start and why (see `checks/safety-nets.md`), and which modules can't be tested against a database at all (e.g. a module that starts its own message bus at start-up).
6. **Report it** in `diagnosis/00-test-readiness.md`, in plain English: what existed, what was added, what isolation was done, and what still can't be tested and why. It becomes the report's section 0.
7. **Feed forward.**
   - Inspectors receive the inventory and note whether a behaviour is already tested.
   - The Tester reproduces findings as tests.
   - Every plan of action names its regression test.

### Phase 1: reconnaissance (in parallel with Phase 0)

The inputs come from the Start step. If only a development database exists, label it as such, and mark data and performance checks as limited.

Record everything in `diagnosis/01-recon.md`, taking every fact from a command or a file, not memory. **Also emit the machine-readable Capability Manifest `manifest.json` (`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md` §1)** — every field resolved by a command, never by belief: repo commit + tree-state, stack versions + `$DLL` path, and each capability (db copy + canary, backend + url, low-priv account, App Insights, private feeds, and tool presence/versions for gitleaks/ilspycmd/dotnet/sqlcmd/playwright), plus the mandatory declared `severity_target`. The manifest is what makes two runs comparable (same manifest ⇒ comparable; differences are expected only where capabilities differ). Recon prose and the manifest agree because both are built from the same commands.
- stack and versions (.NET, ABP, the **Shesha version**, Node, DBMS). **Resolve the Shesha version from `backend/Directory.Build.props` `$(SheshaVersion)` (and `project.assets.json`), not from a prose file** — a starter's `VersionInformantion.md` / README often states the *starter-template* version (e.g. "v0.30.1") which is NOT the framework version, and the per-project `.csproj` references the MSBuild variable `$(SheshaVersion)` rather than a literal, so a csproj grep for a version number finds nothing. Cross-check with `@shesha-io/reactjs` in the portal. **Also record the DBMS(es):** a Shesha starter is often **dual-DBMS (SQL Server + PostgreSQL)** — note which the system actually runs, because the SQL checks and tooling assume SQL Server (see `checks/sql.md`). **Verify VCS state with `git rev-parse` / `git status`, not the environment banner** — the harness "Is a git repository" line is sometimes wrong (it has reported `false` for a repo with thousands of commits).
- **module map (multi-module systems):** list the back-end modules and front-end portals (and their individual package versions — portals drift). Emit this map so inspectors partition by module; the `team.md` ID ranges assume one or two modules, so for N modules give each module its own ID band (e.g. `FORM-<module#>00..`) rather than the fixed two-way split.
- the main entities and roles, and how access is meant to be restricted;
- deployment history (migration dates, form configuration versions, config packages);
- telemetry (sampling, what is logged, audit, retention);
- QA vs production drift where known;
- **what the copy holds:** say up front if its transactional tables are empty or near-empty. Data-dependent findings then need an e2e reproduction with seeded records, and performance checks are limited;
- **system size — calibrate to it.** Record whether this is a large production system or a small/demo/training app (file count, entity count, whether telemetry exists, table sizes). On a tiny app with near-empty tables and no App Insights, performance and scale findings are **CODE-ONLY, forward-looking, low severity** — real patterns worth a line, not incidents; do not inflate them, and don't expect Phase 3 telemetry proof or prod/QA drift to apply. Match the depth of the review to the system.
- **working-tree state:** record it up front. If the tree is already dirty (uncommitted work — often the very feature under review), that is **normal, not an error**: note the pre-existing changes, inspect the **working-tree** state (the developer's current intent), and treat "leave `git status` unchanged before and after" as *don't introduce changes of your own*, never as a precondition that the tree be clean. **If the target is not a git repository at all** (some checkouts aren't — confirm with `git rev-parse`), the read-only guarantee can't be a git diff: it is "wrote nothing under the app root", verified by not writing (and by putting all output outside the app folder). State which guarantee applies. **Third state — a git repo with zero commits** (`git rev-parse` true but no HEAD, everything untracked, common on a fresh/scratch/test-harness repo): `git ls-files` and history are empty, so any check that keys on "tracked" or "committed" silently passes. In this state treat **every present file as in scope** and base the dump (`safety-nets`) and secret (`SEC-E`) checks on the **working tree**, not `git ls-files`; and the re-run comparison ("compare HEAD with the previous run's commit") does not apply — there is no HEAD.
- the route list without starting the app, where available (`Web.Host/obj/<config>/<framework>/ApiEndpoints.json`);
- **on a re-run:** compare HEAD with the previous run's commit first, and list what changed, so findings can be marked fixed, still open or new.

### Phase 2: inspection, one owner per topic

Before launching, the main session assigns **topic ownership** and **ID ranges** so findings aren't duplicated (`references/team.md`, "Topic ownership" and "ID ranges"). Inspectors that spot something in another owner's topic add a one-line "handover" instead of a full finding, and refer to other areas by topic, not by guessed ids.

**Run the settings probe first** (`checks/security.md` SEC-I). On Shesha 0.43.x–0.44.x it can find secrets readable anonymously (confirmed present through 0.44.2 by decompile; re-verify per version). A hit is an urgent stop (see "What the user sees during a run").

Launch the specialists in `references/team.md` **in parallel**. Each gets its check file, `01-recon.md`, `00-test-readiness.md`, its topic list and `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`:

| Role | Check catalogue |
|---|---|
| DevOps engineer | `checks/operations.md`, `checks/safety-nets.md`, App Insights queries |
| Developer | `checks/code.md` |
| SQL developer | `checks/sql.md` plus `sql/diagnostic-queries.sql` |
| ORM / Shesha specialist | `checks/orm-shesha.md` |
| Security reviewer | `checks/security.md` |
| Forms analyst | `checks/forms.md` |

Each returns findings in the `${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md` format, plus "checked and fine", questions for the BA and concerns for the PM. Subagents may be unable to write files, so **the main session saves** each area file to `diagnosis/findings/<area>.md`, using the method in `references/team.md` → "Saving hand-backs". Hand-backs are saved, not shown to the user. Inspectors leave the working tree exactly as they found it: check `git status` before and after.

### Phase 2b: fact-check (mandatory)

Before merging, a fresh agent checks every critical and high finding against the code and data it cites, and returns confirm, correct or downgrade per finding. It is never skipped. Its brief is in `references/team.md` ("Fact-checker").

### Phase 3: proof

The **Tester** reproduces every critical and high finding, plus every anomaly, **as a test** where the harness reaches it:
- an integration test for back-end rules, access checks and data handling;
- an e2e spec for user journeys and forms.

The test fails today and must pass after the fix. Keep these tests on the `tlc/test-coverage` branch; they become the regression tests. Follow `${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`: synthetic `ZZ-PROBE` users and records, backup and restore, code matching the deployed version when proving production behaviour.

**Access-control findings are proven over HTTP** (see the 0.43 non-virtual caveat in `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`).

**A failing test counts as proof only when it fails for the right reason.**
- The assertion message must show the finding's behaviour (e.g. "expected 403, got 200 with 12 rows"), not a login failure, a setup error, a timeout or a missing seed.
- Record the reason per test: test name, result, and the one-line failure message. It goes in the report's Test index.
- A test can also **disprove part of a finding** (e.g. an anonymous read reproduced while the anonymous write was refused). Then update the evidence level, the finding's title and wording, and its severity if needed, in the area file and the report.

In deep mode, add App Insights (`references/appinsights-queries.kql`: aggregates, sampling-weighted, digits masked). **Escalate for production data** only when a QA-proven finding is serious and likely present in production, for example lost work, data exposure or a large failure rate. Explain why, ask the user to escalate to the IT Manager, and record the decision.

### Phase 4: consolidation

The **Senior Engineer** merges the area files, and the main session writes the result to `REPORT.md`. Then the **Architect** reviews it, and the main session writes the review into the report's "Architect review" section and applies its re-ranks. Their briefs are in `references/team.md`. In short:
- **Senior Engineer:** merges duplicates (the surviving id lists its sources; merged-away ids become `duplicate → <id>`); separates **framework defects** for the Shesha team report; ranks **severity first** (critical, high, medium, low), then by harm: life-safety or lost work, data exposure and security, data integrity, reliability, performance, maintainability; writes each plan of action (framework-native fix, size, risk, regression test, how to verify); proposes the fix groups; collects BA questions and PM concerns; builds the learning digest.
- **Architect:** root causes (RC1, RC2, …) with structural fixes and standing regression guards; the fix sequence, separate from severity; the emergency shortcuts register; ranking challenges; consistency of cross-references; PM concerns.

### Phase 5: reports

- **`diagnosis/findings.json` — the canonical, diffable output, emitted first; `REPORT.md` is derived from it** (`${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md` §8). One record per finding: `{finding_id, check_id, area, anchor, evidence_level, execution_class, severity, severity_inputs, plan_id, root_cause, fix_order_rank, sources[], not_assessed_reason}`, sorted canonically (severity band → area → check_id → anchor), tagged with the manifest `commit_sha` + hash. This single source is what prevents a finding carrying two different evidence levels in two files, and it is the acceptance-test diff surface (`harness/`). For the migrated areas (security first) ids are `CHECK-ID@anchor` with no ordinal; other areas keep `<PREFIX>-<n>` until migrated.
- `diagnosis/REPORT.md` from `${CLAUDE_PLUGIN_ROOT}/shared/templates/report.md`, rendered **from `findings.json`**. The report shape (size target, full, compact and one-line findings, Test index) is in the comment at the top of that template.
- `diagnosis/SHESHA-TEAM-REPORT.md` from `${CLAUDE_PLUGIN_ROOT}/shared/templates/shesha-team-report.md`, if there are framework defects, including candidates still to reproduce.
- Tell the user in a few lines that the report is ready, with its path and the three things that matter most. Then start the walkthrough (or, in `--dev-mode-only` mode, present the board as a proposal).

### Phase 6: walkthrough

In `--dev-mode-only` mode, only if the user asks; the board stays a proposal. Otherwise follow `references/walkthrough.md`. For each finding, in rank order, offer **Agree** or **Discuss**.
- **Discuss:** talk it through, check the user's information against the code or data, adjust the finding and its plan, and record why. The finding is then agreed in its adjusted form, or marked intended, deferred or rejected, with the reason.

When every finding is settled, present:
- the agreed plan in fix order;
- the proposed board: one parent work item and a short list of consolidated tasks (`references/work-items-and-prs.md`);
- the PR grouping.

Then prompt **"Let's begin!"**

### Phase 7: fix

Not in `--dev-mode-only`. Reached on "Let's begin!" (`--interactive`), or straight away for the allowlisted fixes (`--auto-fix`).
1. Create the parent work item **`{SystemName}-TLC-Fixes`** and its tasks, consolidated: one task per fix group, not one per finding (`references/work-items-and-prs.md`).
2. **Use the security instruments for the fixes they own** (`references/skills-to-use.md`): `hardening-shesha-app --apply` for the app-level settings (one commit per check, dry-run diff first); `shesha-access-control` (`implement`) for the permission model — `api-permissions-manifest` rows mapped to existing permission-definitions, and global specifications, written **only after** decompiling to verify the real `ShaSpecification`/permission-checker API for the project's exact Shesha version; and `shesha-access-control`'s **authorisation inventory test** as the standing CI guard for every access-control root cause. Everything else uses the framework-native builders already listed.
3. Hand each remaining task to an engineer session with:
   - its findings and plan;
   - its reproducing and regression tests;
   - `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`;
   - the instruction: "use the framework's native mechanism".

   Never run two engineers on the same files.
4. Each fix ships with its tests passing; the e2e suite runs before a PR is pushed **only when e2e is enabled** (`--deep`/`--e2e`), otherwise the integration tests gate it. PRs follow `references/work-items-and-prs.md` (links, description, rollback export, one open package per form).
5. The correspondent (the main session) tracks progress against the finding IDs and reports to the user. **In `--auto-fix` only the allowlisted mechanical fixes ship automatically** (SKILL.md Modes); everything judgement-heavy stays a finding.

### Phase 8: learn (every run)

Follow `references/self-improvement.md`.
- **Collect.** During the run, record candidate learnings in `diagnosis/LEARNINGS.md`: new problem types, better detection or proof methods, framework caveats, generally applicable user corrections, and faults in the skill itself.
- **Write the upgrade.** At the end of the run, generalise them, with no system names, data or secrets. Add them to the right skill files, validate, and run the secret and PII scan.
- **Raise the PR.** Ask *"Raise the skill-upgrade PR for review by Igor Kors?"* On yes, open it against `Boxfusion/Boxfusion-plugins` with a version bump and the review requested from **igorkors-boxfusion**.
- **Never merge it yourself.** It is released when he approves.

## Files

- `TRIAL-NOTES.md`: trial lessons and the changelog per run (not loaded during runs).
- `references/vision.md`: the product owner's requirements (V1–V28). Read when changing the skill, not during runs.
- `references/team.md`: role briefs, topic ownership, ID ranges, saving hand-backs, fact-check, how to launch and consolidate, staffing.
- `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`: the Shesha / ABP way to do each kind of fix; known caveats; shortcuts to flag.
- `references/work-items-and-prs.md`: the board structure, task consolidation and PR conventions.
- `references/self-improvement.md`: how the skill turns new problem types into reviewed upgrades (reviewer: Igor Kors).
- `${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`: QA first, production escalation, isolation and canary, PII, synthetic logins.
- `references/skills-to-use.md`: existing skills per phase and role, install commands, and slots for new ones.
- `references/walkthrough.md`: Agree / Discuss, then "Let's begin!".
- `references/appinsights-queries.kql`: aggregate, PII-masked telemetry queries.
- `checks/*.md`: the check catalogue per area: `code.md`, `forms.md`, `operations.md`, `orm-shesha.md`, `safety-nets.md`, `security.md`, `sql.md`.
- `sql/diagnostic-queries.sql`: SQL Server checks. Run with `sqlcmd -i`.
- `${CLAUDE_PLUGIN_ROOT}/shared/templates/report.md`, `${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`, `${CLAUDE_PLUGIN_ROOT}/shared/templates/shesha-team-report.md`.
