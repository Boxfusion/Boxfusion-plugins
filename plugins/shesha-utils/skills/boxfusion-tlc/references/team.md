# The diagnosis team

The main session is the user's **correspondent**: it briefs the team, relays findings and decisions, and keeps the conversation free of tool noise. The specialists do the hands-on work.

## What the user sees during a run

The rules are in SKILL.md ("What the user sees during a run"): one-line progress, the report, the walkthrough, and an urgent stop as the one exception. Hand-backs are never echoed.

Tell every agent this in its brief: *"Your result is saved to a file, not shown to the user. Return it in the requested format only, with no preamble."*

**Degrade gracefully when an inspector doesn't finish.** Inspectors time out, are force-handed-back, or crash — on a real run you will not always get all of them. When some return and some don't: deliver what returned, mark each missing area explicitly **NOT-RETURNED** (never silently drop it, and never fabricate its findings from guesswork), note it in the report's coverage summary, and offer to re-run the missing areas. A partial, honestly-labelled report beats a late or invented-complete one. The consolidation and the user-facing summary both say which areas are missing.

## Saving hand-backs

Subagents may be unable to write files, so the main session saves their results.
- **Ask for text with a separator.** The brief says: *"Return the file content only, starting with a line `=====BEGIN <file name>=====` and ending with `=====END=====`."* For two files (e.g. the report and a board), use one pair of lines per file.
- **Large hand-backs are persisted** by the harness to a tool-results file instead of being shown in full. Don't re-type or re-generate them. Split the persisted file with the separator lines, e.g.
  ```bash
  f=<persisted tool-results file>
  s=$(grep -n '^=====BEGIN' "$f" | head -1 | cut -d: -f1)
  e=$(grep -n '^=====END' "$f" | head -1 | cut -d: -f1)
  head -n $((e-1)) "$f" | tail -n +$((s+1)) > diagnosis/REPORT.md
  ```
  Then check the saved file's first and last lines and its line count.
- Small hand-backs can be saved with the Write tool directly.
- **The orchestrator owns persistence, and on a read-only/propose-only run it saves to the external run folder, never inside the app repo** (SKILL.md "Outputs", hard rule). Resolve the save path to that external folder before writing; a sweeper/inspector subagent cannot Write at all, so don't rely on it to save — it returns text, you persist it.
- Never show the saved content to the user.

## How to launch

- **Start of the run:** launch the Phase 0 test-coverage staff **and** recon, then the inspectors, without waiting for one another. Phase 0 and Phases 1–2 run side by side with separate staff. Only Phase 3 waits for the harness.
- **Inspection (Phase 2):** launch the inspectors as parallel subagents (Agent tool, `general-purpose`) in one message.
  - Each gets:
    - its brief below and its `checks/<area>.md`;
    - `diagnosis/01-recon.md` and `diagnosis/00-test-readiness.md` (as far as it exists; the inventory arrives early, the baseline later);
    - `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`;
    - **its topic list** (topic ownership, below);
    - **its ID range** (below).
  - Inspectors **return their findings as text**, and the main session saves `diagnosis/findings/<area>.md` ("Saving hand-backs" above).
  - They only read and never start the app. They leave the working tree as found: check `git status` before and after, and delete anything they created.
- **Phase 0 test coverage, proof (Phase 3) and fixing (after "Let's begin!"):** use separate sessions (start_session), one Tester or Engineer per independent piece. If that tool isn't available, use background subagents, each in its own worktree.
  - They need a running backend and long reproductions, and the user may want to talk to them directly.
  - Never run two writers on the same database copy or files at the same time.
- **Fact-check (Phase 2b, mandatory):** one fresh subagent re-checks every critical and high claim and returns corrections (brief below).
- **Consolidation (Phase 4):** one Senior Engineer subagent merges the findings and returns REPORT.md as text with separator lines, which the main session saves. Then one Architect subagent reviews the merged result, and the main session writes the review into the report. Run them in sequence.

## ID ranges

One table for areas, ID prefixes, division skills and owners. The `--area` flag and the finding's **Area** field use the same area names. The conductor **invokes the division skill by name**; each skill owns its own check catalogue.

| Area (`--area`) | ID prefix | Division skill (invoke by name) | Owner |
|---|---|---|---|
| `code` | `CODE-` (front end as its own range, e.g. `CODE-100..`) | `shesha-code-review` | Developer |
| `sql` | `SQL-` | `shesha-sql-review` | SQL developer |
| `orm` | `ORM-` | `shesha-orm-review` | ORM / Shesha specialist |
| `security` | `SEC-` | `auditing-application-security` (detect) · `hardening-shesha-app`, `shesha-access-control` (fix) | Security reviewer |
| `ops` | `OPS-` (safety nets included) | `shesha-operations-review` | DevOps engineer |
| `forms` | `FORM-` | `shesha-forms-review` | Forms analyst |
| `unused` | `UNUSED-` | `shesha-unused-code-audit` (propose-only; cross-signal: code + forms + telemetry) | Maintainability |

When two inspectors share a prefix, give each a **non-overlapping range** in the brief, e.g. Forms by module: `FORM-1..39` for one module group and `FORM-40..` for the rest. Never "start at 20": the first analyst may reach 20 and the ids clash. Leave gaps; the Senior Engineer doesn't renumber.

> **The security division does NOT use numeric ranges.** Under `--security-only` (and for the `security` area generally once migrated), finding ids are `SEC-X@<anchor>` per `${CLAUDE_PLUGIN_ROOT}/shared/operating-standard.md` §3 — no `-1/-2/-3` ordinal, multiplicity carried by the anchor. This removes the discovery-order divergence numeric ranges cause. See "Security division — deterministic briefing & orchestration" below, which supersedes the numeric-range and "mark evidence level honestly" guidance for security. The other areas migrate to the same scheme as they are hardened.

## Topic ownership

Assign topics before launching, so each issue is written up once. Inspectors who see something in another owner's topic add a one-line **handover** ("Security: GetLatestApplication takes any personId, see CODE file X:line"), not a full finding, and never guess another area's ids.

| Topic | Owner |
|---|---|
| Who may see or do what (authorisation, scoping, generic CRUD exposure, anonymous endpoints), secrets, personal data | Security |
| Fetching data (over-fetch, search, paging, N+1, name-based lookups) | ORM / Shesha |
| Form behaviour, form scripts, form-only rules | Forms |
| Database objects, indexes, views, procedures, SQL scripts | SQL |
| Pipelines, configuration, dependencies, telemetry, jobs, messaging, notifications delivery | DevOps |
| Application logic, error handling, transactions, side effects, structure | Developer |
| Bypassing the framework (custom JS, raw SQL, hand-made configuration) | the owner of the area where it happens |

Every brief includes the ground rules from SKILL.md (including **framework first**), the data rules from `${CLAUDE_PLUGIN_ROOT}/shared/safety-and-data-access.md`, the finding format (`${CLAUDE_PLUGIN_ROOT}/shared/templates/finding.md`), and: *"List what you checked and found fine. Keep questions for the BA and concerns for the PM separate from findings. Mark every finding's evidence level honestly."*

**Put the secret-redaction rule in the brief verbatim — the inspector will not inherit it.** The data rules live in a reference the inspector may not read closely; a reference is not enough, as an inspector once quoted literal API keys, a JWT key, a storage key and a DB password straight into its hand-back. Every inspector (and fact-checker, tester, environment-lead) brief must carry this exact line: *"Never reproduce a secret value anywhere in your hand-back — not keys, tokens, connection strings, passwords or API keys. Report presence + length band only (e.g. 'SecurityKey present, ~32 chars'). The same for personal data: counts and categories, never the values."* And the **orchestrator scrubs before persisting:** before saving any hand-back to a run file, scan it for obvious secret shapes (long base64/hex runs, `Password=`, `AccountKey=`, `ApiKey`, `SecurityKey` followed by a value) and redact to `‹redacted, N chars›` — never write a literal secret to disk even if an inspector slips one through.

## Roles

### DevOps engineer
**Looks at:** the repo setup, CI and pipelines, configuration and secrets in config files, dependencies, and App Insights.
**Division skill:** `shesha-operations-review` (operations + safety-nets).
**Instrument:** runs **`hardening-shesha-app`** in scan mode for the app-level security settings (JWT lifetime, sign-out/token-blacklist, failed-login lockout, Hangfire dashboard) and relays each FAIL/WARN with its one-line *why*; the fixes themselves wait for the fix phase (or apply under `--auto-fix`).
**Queries:** `${CLAUDE_PLUGIN_ROOT}/shared/appinsights-queries.kql`. Always weight counts by `itemCount`, because App Insights samples.
**Answers:**
- What fails in production, how often and where?
- What is slow?
- What happens on each request (SQL calls per request)?
- Which background jobs, SMS and integrations fail?
- Which integrations fall back to package defaults, and where do those point (OPS-H)?
- Is the telemetry itself adequate?

### Developer
**Looks at:** application code, back end and front end.
**Division skill:** `shesha-code-review`.
**Answers:**
- Where does the code violate basic engineering practice in ways that cause real problems?
- Which patterns repeat?

### SQL developer
**Looks at:** schema, indexes, stored procedures, functions, views, raw SQL in code, and migrations.
**Division skill:** `shesha-sql-review` (carries the SQL checks and the diagnostic queries; run against the isolated local copy).
**Answers:**
- Which queries will degrade or break as data grows?
- Which procedures are wrong, slow or dangerous?
- What grows forever?

### ORM / Shesha specialist
**Looks at:** entity mappings, how data is fetched (dynamic CRUD, GraphQL, `GetAll`, repositories, lazy loading), and specifications and filters.
**Division skill:** `shesha-orm-review`.
**Answers:**
- Where does the system fetch far more data than it shows, search every field, skip paging, or load related records the slow way?

### Security reviewer
**Looks at:** authentication and authorisation, endpoint permissions, client-trusted parameters, secrets, generic endpoints, SignalR authentication, and data exposure.
**Division skill:** `auditing-application-security`.
**Instruments:** runs **`auditing-application-security`** for the endpoint/entity/form/permission catalogue, the low-privilege and anonymous probes, and the curated probe matrix (`skills-to-use.md`); builds on its catalogue rather than re-cataloguing by hand. Where the skill isn't installed, falls back to `harden-permissions` + `security-review` and records the gap.
**Runs first:** the settings probe (SEC-I) and the framework-table probe (SEC-C), including the curated matrix (OtpAuditItem reset tokens, the hidden endpoints). A secret readable anonymously is an urgent stop.
**Never only as the admin, never only app entities:** probes every framework, ABP and Enterprise entity's generic CRUD signed out and as the low-privilege user (SEC-FW); probes, per non-admin role, whether it can take over an administrator account (SEC-ESC); after an upgrade, diffs permission records and restarts to prove custom records survive (SEC-DRIFT, SEC-RESET), and checks forms for removed endpoints (SEC-GONE). Records modules on branches not under review as a coverage gap.
**Runs the cross-area pass (SEC-K):** takes the Forms/Developer/ORM handovers about workflow and status writes and traces each through the live BPMN to the server step that really runs — this is where approve-your-own, status-from-browser, gates-after-submit and test/debug payroll endpoints are caught, which the endpoint catalogue alone misses.
**Answers:**
- What can a logged-in (or anonymous) user see or do that they shouldn't?
- What secrets are exposed?
- Can any non-admin role take over an administrator account?
- Which *business flows* can be driven or skipped from the browser (SEC-K)?

### Forms analyst
**Looks at:** Shesha form configurations, the **live versions in the environment's database, not the repo copy**, and their scripts and data sources.
**Division skill:** `shesha-forms-review`.
**Answers:**
- What is each form meant to do, and what does it actually do?
- Where do form scripts cause wrong data, failed saves or wasted requests?

### Tester (Phase 3)
**Proves or disproves** findings on the local copy, **as tests** wherever the harness reaches the behaviour: integration tests via the project's test projects (`run-integration-tests` to run them), e2e specs via the e2e chain.
- Uses synthetic users and records.
- Backs up before changes and restores after.
- Uses code matching what is deployed.
- Reproduces through the UI where users would hit the problem, and through the API otherwise. **Access-control findings go over HTTP** (the 0.43 non-virtual caveat in `${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`).
- **Checks that each failing test fails for the right reason.** The assertion message must show the finding's behaviour, not a login, setup, seed or timeout error. Fix the test until it does, or record it as "not yet a proof".
- **Returns one row per test:** finding ID, test name and path, result, the one-line failure message, and the verdict: reproduces / partly disproves / disproves. A partial disproof (e.g. anonymous read reproduced but anonymous start refused) is reported as such, so the finding's wording and evidence can be corrected.
- Tightens weak assertions in the tests it names, e.g. `Should.ThrowAsync<Exception>` becomes the specific exception type.
- Reports the evidence level and exactly what still needs logs.

### Fact-checker (Phase 2b, mandatory)
**Verifies** every critical and high finding against the code and data it cites, and returns confirm, correct or downgrade per finding, with the evidence. It doesn't add new findings. For each finding it checks:
- **the code:** does it say what the finding claims? Read the body before accepting "empty", "missing" or "never called". Validating input is not authorising the caller.
- **the counts:** do they respect soft-delete flags (`IsDeleted`), live status (`VersionStatus` Live, `IsLast`), and active or retired versions? Re-run the count with those filters.
- **the harm path, end to end:** follow the claimed consequence through to what actually happens, e.g. read the workflow definition (BPMN) to see which step really follows a decision, or which server step runs next and what it checks.
- **framework behaviour:** where the claim depends on what Shesha does (timing of side effects, defaults, permissions), check the pinned package (decompile with `ilspycmd` if needed).

### Senior Engineer (Phase 4)
**Merges** all findings and writes the draft `REPORT.md` from `${CLAUDE_PLUGIN_ROOT}/shared/templates/report.md`:
- de-duplicates and links causes to effects;
- ranks by severity, then harm. **Severity stays separate from sequence:** never raise a finding only so it lands first;
- writes each plan of action: a framework-native fix (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md`), size (S/M/L), risk, the regression test, how to verify;
- separates Shesha framework defects (for `SHESHA-TEAM-REPORT.md`);
- proposes the consolidated fix groups that become the work item's tasks (`work-items-and-prs.md`), and gives every finding its Task;
- builds the learning digest of recurring patterns.

**Report shape:** follow the comment at the top of `${CLAUDE_PLUGIN_ROOT}/shared/templates/report.md` (size target; full, compact and one-line findings; Task column; Test index; duplicates appendix).

### Architect (Phase 4)
**Reviews** the Senior Engineer's draft and returns the "Architect review" section, which goes right after the summary:
- **Root causes (RC1, RC2, …):** the causes behind clusters of findings, e.g. "there is no shared access-scope rule, so every endpoint re-implements or forgets it". A table: root cause, findings it explains, framework-native structural fix.
- **A standing regression guard per root cause** where one exists. For an access-control root cause, always recommend the **authorisation inventory test** (`auditing-application-security` SEC-C): without it the problem returns with the next endpoint.
- **Fix sequence:** phases with dependencies and the decisions that gate them. Sequence is not severity.
- **Emergency shortcuts register:** each shortcut, why it is an emergency, the native end state, and the follow-up trigger. Distinguish documented framework caveats and operational steps (e.g. credential rotation), which are not shortcuts.
- **Ranking challenges:** raise, lower, keep with a note. Unproven criticals: reproduce before the walkthrough, or word them "the configuration allows…".
- **Consistency:** plans that refer to other groups or tasks point to the right ones; one parent work item name throughout.
- **PM concerns:** release risk, **rollback** and package rules (`${CLAUDE_PLUGIN_ROOT}/shared/framework-standards.md` caveats), skills, rough effort, escalations, and cross-project disclosure for framework-wide issues.
- **Board proposal** (report §10), from the Senior Engineer's fix groups.


## Staffing and parallelism

The aim is a ranked report in about 2 hours for a typical system, and the whole run well under 5 hours, not a day of serial work. Run as much in parallel as the machine allows.

**Two teams at once.** Phase 0 (test coverage and the e2e harness) and Phases 1–2 (recon and the topic owners) start together and run side by side, each with its own staff. Neither waits for the other. Only Phase 3 (proof) waits for the harness.

| Track | Staff | Isolation |
|---|---|---|
| Phase 0 environment | 1 environment lead: access checks first (private npm feed token, logins), database copy, integration isolation, canary, e2e harness (`test-setup`) | Owns the e2e database copy and the running app |
| Phase 0 back-end tests | **1 integration-test engineer per module group.** Group modules so each engineer has a similar load | **Each writer has its own worktree and branch, and its own disposable test database.** Merge into `tlc/test-coverage` at the end |
| Phase 0 e2e plans | 1 plan author once the environment is up (a session opened in the target repo, where the Playwright MCP is registered) | Shares the environment lead's running app; never restarts it |
| Phases 1–2 | Recon, then **up to 8 inspectors**: the 6 roles, with Forms split by module and Code split into back end and front end when the system is large. Split roles get pre-assigned ID ranges | Read only, so they run alongside Phase 0 |
| Phase 2b | 1 fact-checker | Read only |
| Phase 3 | 1 tester per finding cluster, once the harness is ready | Each tester's writes stay on its own synthetic records |
| Phase 4 | Senior Engineer, then Architect (in sequence) | — |

**Resource rule:** at most **3 heavy jobs at once** on a typical developer laptop. Heavy jobs are `dotnet build` and test runs, database restores and imports, and Next.js builds. Readers, planners and inspectors are light and can all run at once. Stagger heavy work, e.g. start each module engineer's build a few minutes apart. Back off if the machine slows.

**Never two writers in one worktree or one database.**

## Canonical briefs, sub-area partitions & orchestration rules

Moved to the shared TLC contract library (single source of truth). Read **`${CLAUDE_PLUGIN_ROOT}/shared/briefs/inspector-briefs-and-partitions.md`** — the canonical security + generic-division inspector briefs (fill only the placeholders), the fixed sub-area partitions, and the orchestration rules (overlap resolution, duplicate-collapse-by-id, persist-then-derive, the two-operator acceptance diff). The conductor fills the placeholders when dispatching; every division skill honours the same briefs, so a team split and a single-operator run merge byte-identically.
