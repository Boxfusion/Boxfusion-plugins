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
    - `references/framework-standards.md`;
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

One table for areas, ID prefixes, check files and owners. The `--area` flag and the finding's **Area** field use the same area names.

| Area (`--area`) | ID prefix | Check file | Owner |
|---|---|---|---|
| `code` | `CODE-` (front end as its own range, e.g. `CODE-100..`) | `checks/code.md` | Developer |
| `sql` | `SQL-` | `checks/sql.md` | SQL developer |
| `orm` | `ORM-` | `checks/orm-shesha.md` | ORM / Shesha specialist |
| `security` | `SEC-` | `checks/security.md` | Security reviewer |
| `ops` | `OPS-` (safety nets included) | `checks/operations.md`, `checks/safety-nets.md` | DevOps engineer |
| `forms` | `FORM-` | `checks/forms.md` | Forms analyst |

When two inspectors share a prefix, give each a **non-overlapping range** in the brief, e.g. Forms by module: `FORM-1..39` for one module group and `FORM-40..` for the rest. Never "start at 20": the first analyst may reach 20 and the ids clash. Leave gaps; the Senior Engineer doesn't renumber.

> **The security division does NOT use numeric ranges.** Under `--security-only` (and for the `security` area generally once migrated), finding ids are `SEC-X@<anchor>` per `references/operating-standard.md` §3 — no `-1/-2/-3` ordinal, multiplicity carried by the anchor. This removes the discovery-order divergence numeric ranges cause. See "Security division — deterministic briefing & orchestration" below, which supersedes the numeric-range and "mark evidence level honestly" guidance for security. The other areas migrate to the same scheme as they are hardened.

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

Every brief includes the ground rules from SKILL.md (including **framework first**), the data rules from `safety-and-data-access.md`, the finding format (`templates/finding.md`), and: *"List what you checked and found fine. Keep questions for the BA and concerns for the PM separate from findings. Mark every finding's evidence level honestly."*

**Put the secret-redaction rule in the brief verbatim — the inspector will not inherit it.** The data rules live in a reference the inspector may not read closely; a reference is not enough, as an inspector once quoted literal API keys, a JWT key, a storage key and a DB password straight into its hand-back. Every inspector (and fact-checker, tester, environment-lead) brief must carry this exact line: *"Never reproduce a secret value anywhere in your hand-back — not keys, tokens, connection strings, passwords or API keys. Report presence + length band only (e.g. 'SecurityKey present, ~32 chars'). The same for personal data: counts and categories, never the values."* And the **orchestrator scrubs before persisting:** before saving any hand-back to a run file, scan it for obvious secret shapes (long base64/hex runs, `Password=`, `AccountKey=`, `ApiKey`, `SecurityKey` followed by a value) and redact to `‹redacted, N chars›` — never write a literal secret to disk even if an inspector slips one through.

## Roles

### DevOps engineer
**Looks at:** the repo setup, CI and pipelines, configuration and secrets in config files, dependencies, and App Insights.
**Check files:** `checks/operations.md`, `checks/safety-nets.md`.
**Instrument:** runs **`hardening-shesha-app`** in scan mode for the app-level security settings (JWT lifetime, sign-out/token-blacklist, failed-login lockout, Hangfire dashboard) and relays each FAIL/WARN with its one-line *why*; the fixes themselves wait for the fix phase (or apply under `--auto-fix`).
**Queries:** `references/appinsights-queries.kql`. Always weight counts by `itemCount`, because App Insights samples.
**Answers:**
- What fails in production, how often and where?
- What is slow?
- What happens on each request (SQL calls per request)?
- Which background jobs, SMS and integrations fail?
- Which integrations fall back to package defaults, and where do those point (OPS-H)?
- Is the telemetry itself adequate?

### Developer
**Looks at:** application code, back end and front end.
**Check file:** `checks/code.md`.
**Answers:**
- Where does the code violate basic engineering practice in ways that cause real problems?
- Which patterns repeat?

### SQL developer
**Looks at:** schema, indexes, stored procedures, functions, views, raw SQL in code, and migrations.
**Check file:** `checks/sql.md`, run with `sql/diagnostic-queries.sql` against the local copy.
**Answers:**
- Which queries will degrade or break as data grows?
- Which procedures are wrong, slow or dangerous?
- What grows forever?

### ORM / Shesha specialist
**Looks at:** entity mappings, how data is fetched (dynamic CRUD, GraphQL, `GetAll`, repositories, lazy loading), and specifications and filters.
**Check file:** `checks/orm-shesha.md`.
**Answers:**
- Where does the system fetch far more data than it shows, search every field, skip paging, or load related records the slow way?

### Security reviewer
**Looks at:** authentication and authorisation, endpoint permissions, client-trusted parameters, secrets, generic endpoints, SignalR authentication, and data exposure.
**Check file:** `checks/security.md`.
**Instruments:** runs **`auditing-application-security`** for the endpoint/entity/form/permission catalogue, the low-privilege and anonymous probes, and the curated probe matrix (`skills-to-use.md`); builds on its catalogue rather than re-cataloguing by hand. Where the skill isn't installed, falls back to `harden-permissions` + `security-review` and records the gap.
**Runs first:** the settings probe (SEC-I) and the framework-table probe (SEC-C), including the curated matrix (OtpAuditItem reset tokens, the hidden endpoints). A secret readable anonymously is an urgent stop.
**Runs the cross-area pass (SEC-K):** takes the Forms/Developer/ORM handovers about workflow and status writes and traces each through the live BPMN to the server step that really runs — this is where approve-your-own, status-from-browser, gates-after-submit and test/debug payroll endpoints are caught, which the endpoint catalogue alone misses.
**Answers:**
- What can a logged-in (or anonymous) user see or do that they shouldn't?
- What secrets are exposed?
- Which *business flows* can be driven or skipped from the browser (SEC-K)?

### Forms analyst
**Looks at:** Shesha form configurations, the **live versions in the environment's database, not the repo copy**, and their scripts and data sources.
**Check file:** `checks/forms.md`.
**Answers:**
- What is each form meant to do, and what does it actually do?
- Where do form scripts cause wrong data, failed saves or wasted requests?

### Tester (Phase 3)
**Proves or disproves** findings on the local copy, **as tests** wherever the harness reaches the behaviour: integration tests via the project's test projects (`run-integration-tests` to run them), e2e specs via the e2e chain.
- Uses synthetic users and records.
- Backs up before changes and restores after.
- Uses code matching what is deployed.
- Reproduces through the UI where users would hit the problem, and through the API otherwise. **Access-control findings go over HTTP** (the 0.43 non-virtual caveat in `framework-standards.md`).
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
**Merges** all findings and writes the draft `REPORT.md` from `templates/report.md`:
- de-duplicates and links causes to effects;
- ranks by severity, then harm. **Severity stays separate from sequence:** never raise a finding only so it lands first;
- writes each plan of action: a framework-native fix (`framework-standards.md`), size (S/M/L), risk, the regression test, how to verify;
- separates Shesha framework defects (for `SHESHA-TEAM-REPORT.md`);
- proposes the consolidated fix groups that become the work item's tasks (`work-items-and-prs.md`), and gives every finding its Task;
- builds the learning digest of recurring patterns.

**Report shape:** follow the comment at the top of `templates/report.md` (size target; full, compact and one-line findings; Task column; Test index; duplicates appendix).

### Architect (Phase 4)
**Reviews** the Senior Engineer's draft and returns the "Architect review" section, which goes right after the summary:
- **Root causes (RC1, RC2, …):** the causes behind clusters of findings, e.g. "there is no shared access-scope rule, so every endpoint re-implements or forgets it". A table: root cause, findings it explains, framework-native structural fix.
- **A standing regression guard per root cause** where one exists. For an access-control root cause, always recommend the **authorisation inventory test** (`checks/security.md` SEC-C): without it the problem returns with the next endpoint.
- **Fix sequence:** phases with dependencies and the decisions that gate them. Sequence is not severity.
- **Emergency shortcuts register:** each shortcut, why it is an emergency, the native end state, and the follow-up trigger. Distinguish documented framework caveats and operational steps (e.g. credential rotation), which are not shortcuts.
- **Ranking challenges:** raise, lower, keep with a note. Unproven criticals: reproduce before the walkthrough, or word them "the configuration allows…".
- **Consistency:** plans that refer to other groups or tasks point to the right ones; one parent work item name throughout.
- **PM concerns:** release risk, **rollback** and package rules (`framework-standards.md` caveats), skills, rough effort, escalations, and cross-project disclosure for framework-wide issues.
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

## Security division — deterministic briefing & orchestration (`--security-only`)

This section makes the security division reproducible per `references/operating-standard.md`: two operators on the same commit + manifest produce the same `findings.json`. It supersedes, for security, the numeric-range and "mark evidence level honestly" guidance above.

### The canonical security inspector brief (fill only the placeholders)
The orchestrator fills `{check-ids}`, `{repo-commit}`, `{tree-state}`, `{manifest}`; everything else is fixed and non-optional.

```
=====BEGIN SECURITY INSPECTOR BRIEF=====
ROLE: Security reviewer, BoxFusion TLC --security-only. You inspect; you never start the app,
never write a file, never change the working tree (git status identical before/after; delete
anything you create; scratch only in the scratchpad).

YOUR CHECKS (exact closed set — run every one, invent no others; run SEC-I FIRST):
  {check-ids}

REPO: commit {repo-commit} (tree: {tree-state}). Tie every finding to this commit; read the
working tree, not only tracked files.

CAPABILITY MANIFEST (authoritative — do NOT re-detect, do NOT install anything):
  {manifest}
  RULE: a check whose required capability is ABSENT returns NOT-ASSESSED(<reason>) — a first-class
  verdict, never a silent pass, never "fine", never a guess, never a weaker instrument kept at a
  strong level. gitleaks absent => SEC-E recall NOT-ASSESSED(no-secret-scanner), seam-grep = CODE-ONLY.
  No low-priv account => authenticated dimension of SEC-A/B/C/K/L/M/N NOT-ASSESSED(no-low-priv-user);
  anonymous/static stands alone. (See checks/security.md capability-gating table.)

OUTPUT CONTRACT (every finding; operating-standard §§2-6,8):
  1. finding_id = <CHECK-ID>@<anchor>  — NO -1/-2/-3 ordinal. N anchors => N findings. Anchor by
     symbol/role never a raw line number; path lowercased, #Symbol.Member verbatim (§3 forms table).
  2. ANCHOR-REQUIRED: raise a finding IFF the predicate is true AND an anchor exists. No anchor,
     no finding; no anchor-less "smell".
  3. evidence_level from the closed enum via execution_class, MAX achieved for the anchor
     (REPRODUCED>CONFIRMED-IN-LOGS>VERIFIED-ARTEFACT>CODE-ONLY; NOT-ASSESSED(reason) if cap absent).
     An anonymous live probe IS REPRODUCED. Do not upgrade on confidence.
  4. severity SCORED from operating-standard §5 (intrinsic; evidence is NOT an input). Print the
     three inputs: impact_class={} reachability={} data_sensitivity={} => BAND. Score against the
     manifest severity_target, never the copy's data volume. Never raise severity for sequencing.
  5. remediation = the check's templated plan_id (checks/security.md), instantiated with your anchor
     — not free prose. Name the regression test exactly as the check names it.
  6. CANONICAL ORDER: emit sorted by severity band DESC, then check_id ASC, then anchor ASC.
  7. PARTIAL INPUTS => NOT-ASSESSED(reason). Never guess, never infer a value you did not read.
  8. NEVER invent ids, levels, severities or remediations outside these templates.

DATA-SAFETY (verbatim, non-optional): "Never reproduce a secret value anywhere in your hand-back —
not keys, tokens, connection strings, passwords or API keys. Report presence + length band only
(e.g. 'SecurityKey present, ~32 chars'). The same for personal data: counts and categories, never
the values." Compare committed vs deployed secrets by SHA-256 hash only (match/no-match).

SCOPE (--security-only): in scope = the checks listed. Out of scope = performance, ORM scale, SQL
craft, ops/telemetry, forms UX, non-security code quality — name each "not in scope for
--security-only", do not raise it.

RETURN: file content ONLY, no preamble, starting =====BEGIN findings/security.md===== ending =====END=====.
Use templates/finding.md per finding. List "checked and fine" and the NOT-ASSESSED set explicitly.
Keep BA questions and PM concerns separate from findings.
=====END SECURITY INSPECTOR BRIEF=====
```

### Orchestration rules (fixed, not judgement)
- **Fixed sub-area partition** (a team split and a single-operator run merge byte-identically):
  - access-control = SEC-A, SEC-B, SEC-C, SEC-K, SEC-P (JWT-trust), SEC-Q (GraphQL data-plane), SEC-S (tenant isolation) (+ consumed handovers CODE-G-1, CODE-F-1/2, CODE-G-3)
  - secrets & config = SEC-E, SEC-I, SEC-O, SEC-D
  - input & data = SEC-G, SEC-L, SEC-M, SEC-N, SEC-H
  - real-time & messaging = SEC-F, SEC-J, SEC-R (background-job trust)
  Only `{check-ids}` differs between team members. SEC-K stays whole in access-control and consumes its fixed handover list; if a handover-source sub-area didn't run, SEC-K records `NOT-ASSESSED(handover-source-not-run)` for that trace — never guesses it.
- **Overlap resolution (fixed priority, first match wins):** property-authorisation → SEC-L; business-flow/workflow → SEC-K; endpoint authz → SEC-C/B/A; secret → SEC-E/I. The losing check emits a one-line handover referencing the winner's `finding_id`, never a duplicate.
- **Duplicate collapse:** identical `finding_id` ⇒ keep one, union evidence, take the MAX evidence level; take the higher severity only if computed from identical §5 inputs, else flag a determinism defect (don't average). Collapse by id equality only (the id carries the anchor) — no fuzzy/title matching.
- **Persist + normalize:** the orchestrator emits `findings.json` (operating-standard §8 schema) alongside the prose, sorted canonically, each record tagged with `commit_sha` + manifest hash; on a propose-only run, to the external run folder, never under the app root. The markdown is derived from `findings.json` (one source of truth).
- **Acceptance test:** `harness/run-acceptance.ps1` launches two independent operators (`--security-only --static`, same manifest) and diffs; see `harness/`.

## All divisions — deterministic briefing & team-split (generalises the security model)

Every division is now acceptance-proven deterministic the same way security is: two independent operators on the same commit + manifest produce byte-identical `findings.json` (frozen references in `harness/<area>-PASS-*.json`). A team can split **any** division across members, or one person can run the whole division, and the merged result is identical. This section is the generic counterpart to the security briefing above — use it for `--area code|orm|sql|operations|forms` (and for splitting those areas across a team).

### The canonical division inspector brief (fill only the placeholders)
Identical in spirit to the security brief; the orchestrator fills `{area}`, `{check-file}`, `{check-ids}`, `{repo-commit}`, `{tree-state}`, `{manifest}`. The output contract, anchor rules, evidence enum, scored severity, canonical order, and data-safety clauses are **verbatim the same** as the security brief above — a division operator differs only in (a) which `checks/<area>.md` is its sole authority, (b) its check-id set, and (c) its area tag on each record. Non-negotiable additions that the overnight hardening proved necessary:

```
=====BEGIN DIVISION INSPECTOR BRIEF ({area})=====
ROLE: {area} reviewer, BoxFusion TLC. Inspect only; never start the app, never write outside the
scratchpad, git status identical before/after.
AUTHORITY: checks/{check-file} is your ONLY spec. Run its decision procedures VERBATIM — zero
judgement, zero improvisation. Where it gives an exact grep, run that exact grep; do not widen,
narrow, or add a clause qualifier it does not state.
YOUR CHECKS (exact closed set): {check-ids}
REPO: commit {repo-commit} (tree {tree-state}). CAPABILITY MANIFEST (authoritative, no re-detect): {manifest}
  Absent capability => NOT-ASSESSED(<reason>) at the check's fixed anchor — first-class verdict, never a silent pass.
OUTPUT CONTRACT: finding_id=<CHECK-ID>@<anchor> (no ordinal; N anchors => N findings; anchor a
  symbol/role never a line number; the anchor NEVER re-prepends the check id; a `=none` empty verdict
  anchor is literally "none"). evidence from the closed enum (absence/zero-match grep => CODE-ONLY;
  a measured PRESENCE count => VERIFIED-ARTEFACT). severity SCORED intrinsically (§5), evidence is not
  an input. A `sln:<token>=<n>` tally is a context metric => severity Info, plan_id null. Info / empty
  / NOT-ASSESSED records carry plan_id null. A sub the check marks NON-DETERMINISTIC => emit tagged
  non_deterministic:true (the normalizer drops it). Handovers to another area are NARRATED ONLY — never
  emit another area's record in this division's findings.json. Canonical order: severity DESC, check_id
  ASC, anchor ASC.
RETURN: findings.json (bare array) to {out-path}; file content only, no preamble.
=====END DIVISION INSPECTOR BRIEF ({area})=====
```

### Fixed sub-area partitions (a team split and a single-operator run merge byte-identically)
Only `{check-ids}` differs between team members; every other brief field is shared. Handover records are narrated by the detecting area and scored by the receiving area — if a handover source didn't run, the receiver records `NOT-ASSESSED(handover-source-not-run)`, never a guess.

- **CODE** (`checks/code.md`):
  - error & flow = CODE-A, CODE-B, CODE-C
  - structure & patterns = CODE-D, CODE-E, CODE-H
  - front-end & dead code = CODE-F, CODE-G (CODE-F-1/CODE-G-1 narrate-only → security owns them)
  - tests & predicates = CODE-I, CODE-J (CODE-J + CODE-A null-deref + CODE-D semantic-dup + CODE-G import-graph are NON-DETERMINISTIC, dropped from the diff)
- **ORM** (`checks/orm-shesha.md`):
  - query shape = ORM-A, ORM-B, ORM-C, ORM-D, ORM-H
  - exposure & authz handover = ORM-E, ORM-I (ORM-E → SEC-C)
  - lifecycle & session = ORM-F, ORM-G, ORM-J, ORM-K
- **SQL** (`checks/sql.md`):
  - craftsmanship (static) = SQL-C (16 vectors; `groupby-hiding-dup` NON-DETERMINISTIC)
  - physical & growth (DATA-LEVEL → NOT-ASSESSED static) = SQL-A, SQL-B, SQL-D, SQL-E
  - integrity & release path = SQL-F, SQL-G, SQL-H
- **OPERATIONS** (`checks/operations.md`):
  - telemetry-gated (→ NOT-ASSESSED(no-telemetry) static) = OPS-A, OPS-B, OPS-D, OPS-E
  - static config & scheduling = OPS-C, OPS-F, OPS-G, OPS-H
- **FORMS** (`checks/forms.md`):
  - repo-static = FORM-F (F2 cross-module + per-field parity NON-DETERMINISTIC), FORM-D server-validator inventory
  - DB-gated (→ NOT-ASSESSED(no-db-copy) static) = FORM-A, FORM-B, FORM-C, FORM-E, FORM-G

### Orchestration rules (same as security)
Overlap resolution, duplicate-collapse-by-id, persist-`findings.json`-then-derive-markdown, and the two-operator acceptance diff are identical to the security section above. Each division's frozen PASS reference (`harness/<area>-PASS-{A,B}.json`) is the regression baseline: a check-file edit that changes a division's output must be re-accepted (two fresh operators, empty diff) before it ships.
