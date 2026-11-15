# Coverage, framework entities, privilege escalation, upgrade drift and the re-audit

Read at Step 1 (branch coverage), Step 7 (framework entities, privilege escalation) and
whenever the audit follows a framework upgrade or a merge of security fixes (drift and the
re-audit gate).

Every section here exists because a first audit passed something that a re-audit after the
merge found a week later. The lessons are generalised; no system is named.

## Contents

1. Branch and module coverage (Step 1)
2. Framework-entity exposure (Step 7, check SEC-FW)
3. Privilege escalation to an administrator account (Step 7, check SEC-ESC)
4. Upgrade drift: widened rules and start-up resets (checks SEC-DRIFT, SEC-RESET)
5. Removed endpoints still called by forms or the front end (check SEC-GONE)
6. The post-merge re-test and re-audit gate
7. Comparing two runs honestly

---

## 1. Branch and module coverage (Step 1)

**What went wrong.** A system shipped two modules, each a whole product, from a long-lived
feature branch that never merged into the release branch. The audit and every security fix
targeted the release branch. Those modules had none of the security work, and their forms
were still in the shared database, so the re-audit reported their rows as noise.

**Do this at Step 1, before anything else is scanned:**

```bash
git fetch --all --prune
git for-each-ref --sort=-committerdate --format='%(refname:short) %(committerdate:short) %(subject)' refs/remotes | head -40
# for each long-lived branch that is ahead of the release branch:
git log --oneline <release>..<branch> | wc -l
git diff --stat <release>...<branch> -- '*.csproj' '*Module.cs' 'backend/src/*' | tail -5
```

Record a **coverage table** in `recommendations-index.md` and in `_index.json`
`inputsMissing`:

| Branch | Ahead of release by | Modules / projects only on it | Deployed anywhere? | In this audit? |
|---|---|---|---|---|

- A branch is "live or unreleased product" when it adds a module project, a `*Module.cs`, a
  front-end package or migrations, and either something is deployed from it or it is meant to
  ship.
- **Never assume the release branch covers everything.** Modules found only on another branch
  are either audited (a second run on that branch) or listed as **out of scope: not audited**
  — a coverage gap the report states by name. A finding row whose module code is absent from
  the audited branch is a coverage gap, not noise.
- Ask the user which branch each environment deploys from if it is not obvious.

## 2. Framework-entity exposure (Step 7, check SEC-FW)

**What went wrong.** The audit probed app entities, as the administrator only. The built-in
user-account entity's generic CRUD then listed every user account, with user names and email
addresses, to a signed-out caller. An anonymous `Crud/Create` succeeded, and `Update`/`Delete`
got past authorization (404 only at the record lookup). Two built-in bank-account entities
behaved the same. Their records said "Inherited", and the system's default endpoint access
setting was anonymous (check E1), so "Inherited" meant "the whole internet".

**The rule:** framework, ABP and Enterprise entities are this application's exposure. Probe
them through the same generic routes as app entities, signed out **and** as a low-privilege
user:

```
GET    /api/dynamic/<ns>/<Entity>/Crud/GetAll?maxResultCount=1
GET    /api/dynamic/<ns>/<Entity>/Crud/Get?id=<id>
POST   /api/dynamic/<ns>/<Entity>/Crud/Create          (only on a restorable copy)
PUT    /api/dynamic/<ns>/<Entity>/Crud/Update          (an id that cannot exist)
DELETE /api/dynamic/<ns>/<Entity>/Crud/Delete?id=<id that cannot exist>
GET    /api/services/app/Entities/GetAll?entityType=<full class name>   (the generic gateway)
```

Take `<ns>` from the live OpenAPI surface, never from memory: the same entity sits under
`app`, `Shesha` or `Shesha.Enterprise` depending on its assembly.

`run_audit.py` does this automatically: after the first catalogue build it runs
`extend_probe_matrix.py --prune`, whose **framework-entity sweep** (group
`framework-entity-crud`) generates these probes for every package-owned entity with a live
route, then probes again and rebuilds. Priority entities get all four verbs; the rest get
`GetAll`. `verify_run.py` fails the run (`principal-coverage`) if no probe ran signed out, none
ran as the low-privilege user, or the sweep did not run.

Priority entities (extend `PRIORITY_FRAMEWORK_ENTITIES` in `extend_probe_matrix.py` when a
re-audit finds another): user accounts and users; user roles, tokens, logins, claims and
permission settings; role appointments; persons; bank accounts, organisation bank accounts,
financial accounts and transactions; accounts and account invitations; settings and setting
values; audit logs, entity change logs and entity history; file templates; stored files;
notes; notification messages and attachments.

**Read the result:**

- `OPEN` on `GetAll`: quote the field names and the row count (counts only, never values).
- `NOT-FOUND` on `Update`/`Delete` with an id that cannot exist: authorization let the call
  through. That is a finding, not a pass.
- `DISABLED`: 404 with an entity-action record of Disable. `probe.py` reads
  `po-shesha-entity-action.json` to tell this apart from `NOT-FOUND`; without that file a
  switched-off entity is misreported as reachable.
- Also check E1 (the default endpoint access setting). When it is anonymous, every entity or
  action without its own record is anonymous: give each framework entity an explicit record
  so it stays closed whatever the setting.

**Recommendation template** (the fix belongs to `shesha-access-control`, plan
`AC-SEC-FW-lock-framework-entity`):

- **Disable** every action of a framework entity that no form, coded screen or integration
  uses (apply the safety gates in `disabling-unused-endpoints.md`; framework and Enterprise
  screens count as callers, so scan their source or say it was not scanned).
- **Admin-only** (a permission only administrators hold, e.g. role management or
  application settings) for the rest.
- Ship it as a migration that writes the `Shesha.Entity.Action` records, then restart and
  re-probe (section 4: records must survive start-up).

## 3. Privilege escalation to an administrator account (Step 7, check SEC-ESC)

**What went wrong.** Two systems had a path for a non-admin to take over an administrator:

- A framework upgrade made the password-reset endpoint accept a reset permission that
  front-line roles held. Each of three front-line logins reset a test administrator's
  password and then signed in as that administrator.
- An app endpoint for editing staff records synced email, mobile and password-reset methods
  to the linked user account for **any** staff member, including one holding System
  Administrator. A staff-records administrator role could redirect an admin's recovery channels and
  then reset the password.

Endpoint probes as a zero-permission user do not find either: the gap is a specific role
acting on a specific target. **Prove it with a live probe, on an isolated local copy only.**

**Procedure** (state-changing; restorable copy, synthetic accounts, outbound mail and SMS
neutralised first):

1. Create a synthetic target user and give it the System Administrator role.
2. For each non-admin role that exists (or at least: every role holding a user-, person-,
   employee- or role-management permission, and every front-line role), sign in as a
   synthetic member of that role.
3. As that member, try every way to change the target's credentials or recovery channels.
   Take routes from the live OpenAPI surface:
   - reset or set the password (`User/ResetPassword` and any app wrapper);
   - change the sign-in name, email or mobile (`User/Update`, `Person` and `UserAccount` CRUD
     `Update`, and every app endpoint that writes a person or staff record linked to a user);
   - change security questions or answers, or password-reset methods;
   - add a role to anyone, including self (`ShaRoleAppointedPersonActions/AddToRole`,
     `UserRole` CRUD `Create`);
   - read or create user tokens (`UserToken` CRUD).
4. Record the HTTP status **and** re-read the target afterwards. "200 but nothing changed"
   and "403" are both a pass; "200 and the field changed" is SEC-ESC. Stop before triggering
   a real email or SMS: changing the recovery address is already the takeover.
5. Re-check that the target's password, email, phone, roles and tokens are unchanged, and
   that no non-admin holds an administrator role. Revert the copy.

**Recommendation:** remove the over-broad grant where a role does not need it (a business
question: "must front-line staff reset other users' passwords at all?"), **and** add a code
guard: only a System Administrator may change the credentials, sign-in name, recovery email
or mobile, security answers, roles or tokens of a user who holds an administrative
permission. The guard closes paths the grant review misses (a manager's broader
user-management permission, an app sync service). Fix owner: `shesha-access-control`, plan
`AC-SEC-ESC-admin-credential-guard`.

## 4. Upgrade drift: widened rules and start-up resets (SEC-DRIFT, SEC-RESET)

**What went wrong.**

- **Widened (SEC-DRIFT).** A framework upgrade changed the password-reset record from
  "inherits the user-management permission" to "`User-ResetPassword` **or** `User-Manage`".
  An old role grant had been renamed to the first. Requirements are OR-ed, so every role
  holding either passed. Nothing in the application changed.
- **Reset (SEC-RESET).** The upgraded framework hard-codes the user-creation endpoint to
  `User-Manage` and marks the service not configurable. Its bootstrapper re-applies that
  whenever the framework assembly changes, which on a first deploy happens **after** app
  migrations. A tighter custom record, written by a migration, was silently replaced.

**Detect it with two captures and `drift.py`** (`resources/drift.py`):

```bash
# 1. old build vs new build, same database copy
python $R/collect.py --url $OLD --cache drift/before --refresh
python $R/analyze_forms.py --url $OLD --cache drift/before
python $R/collect.py --url $NEW --cache drift/after --refresh
python $R/analyze_forms.py --url $NEW --cache drift/after
python $R/drift.py --before drift/before --after drift/after --json drift/upgrade.json

# 2. new build: first start vs after a restart (records must survive start-up)
python $R/collect.py --url $NEW --cache drift/restart --refresh
python $R/drift.py --before drift/after --after drift/restart --json drift/restart.json
```

`drift.py` reports, sorted and stable:

| Kind | Meaning | Check |
|---|---|---|
| `WIDENED` | a record opened, or now also accepts a permission a non-admin role holds | SEC-DRIFT |
| `RESET` | a record became hard-coded; configuration and migrations can no longer hold it | SEC-RESET |
| `RECORD-GONE` | a record (and any custom rule on it) disappeared | SEC-RESET |
| `FORM-CALLS-GONE` / `FORM-CALLS-MISSING` | forms call a route the new version does not serve | SEC-GONE |
| `GRANTS` | a role's permissions changed (often a framework rename) | context for the rest |
| `NARROWED`, `CHANGED`, `ROUTE-GONE` | review: who lost access, what moved | — |

Exit code 1 on `WIDENED`, `RESET`, `RECORD-GONE` or `FORM-CALLS-GONE`. Pass
`--admin-role "<name>"` when admin roles do not contain "admin", "administrator" or
"configurator" in their names.

Then **probe** each `WIDENED` row as a member of each non-admin role that gained it (section 3
for the credential endpoints). A `RESET` row has no configuration fix: the options are a code
guard, granting the hard-coded permission deliberately, or asking the framework team to make
the record configurable. Say which in the recommendation, and add a unit test that pins the
assumption so the next upgrade cannot change it silently.

Also read `assemblyChecks` in `probe_matrix.json` for the endpoints a framework version
hard-codes, and re-check those after every upgrade.

## 5. Removed endpoints still called by forms or the front end (SEC-GONE)

**What went wrong.** An upgrade removed the generic `Create`/`Update`/`Delete` routes of the
role-appointment entity in favour of a dedicated actions service (`AddToRole`, `Delete`). The
framework's own forms were updated at start-up; the application's forms, and some
framework forms the application had overridden, still called the old routes. "Remove user
from role" and two case screens failed with 404 for everyone, admin included. A form that
treated the failure as fatal also blocked a whole case submission.

It matters for security because the obvious "fix" under time pressure is to re-open a generic
write route.

**Detect:** `drift.py` (`FORM-CALLS-GONE`), plus the stale list from `analyze_forms.py`
(`stale` in `form_analysis.json`: form URLs that are not in the live surface), plus
`scan_frontend.py` hits on removed routes. Probe each one as the admin: a 404 for the admin
on a route a form calls is SEC-GONE.

**Recommend:** repoint the form or screen to the replacement endpoint through the versioned
form lifecycle (the `shesha-form-edit` skill) and export it as a configuration package, so it survives
deployment. Name the replacement route in the finding. Do not re-enable the removed route.

## 6. The post-merge re-test and re-audit gate

The security process ends with this step, before any human testing starts. It runs on the
**merged** code (the branch everything was merged into), on an isolated local copy:

1. **Re-run every existing automated test** — unit and integration tests, e2e and regression
   suites, and every probe suite the exercise wrote. Report pass/fail per suite, before and
   after the merge, and give every failure a reason (regression, known defect, environment,
   stale test). **Do not write new e2e suites in this step.** If none exist, report that as a
   gap in the hand-over ("no e2e or regression suite exists; nothing exercises the screens").
2. **Re-run this audit** on the merged build, with the low-privilege account and the
   framework-entity sweep, then the upgrade-drift captures of section 4 (first start and
   restart) if the merge included a framework upgrade.
3. **Run the privilege-escalation procedure** (section 3) against every role that exists after
   the merge.
4. **Triage** every row into: ours to fix, business decision, framework or package team, or
   noise — and re-probe each before bucketing it. Fix what blocks human testing first.
5. **Report** what blocks human testing, separately from what can wait.

## 7. Comparing two runs honestly

A re-audit that adds a principal (anonymous, low-privilege) or a check is **not like-for-like**
with a run that did not. Say so at the top of the comparison:

- "New" rows from a newly added principal are **newly observed**, not new regressions. Find
  out which by re-probing on the pre-merge build when you can.
- Rows for routes the new version no longer serves (404 to the admin too) are not "fixed";
  they are absent. `probe.py` reports them `ABSENT`; say "absent", never "fixed".
- A source-level flag whose runtime is gated (a dashboard behind an environment check that
  answers 404 or 401 outside Development) is reviewed as passed **with the live evidence**:
  restart outside Development and probe.
- Code-guarded endpoints (`[SheshaAuthorize]` or app attributes the catalogue cannot read) are
  confirmed by probe, not by the catalogue's access column.
