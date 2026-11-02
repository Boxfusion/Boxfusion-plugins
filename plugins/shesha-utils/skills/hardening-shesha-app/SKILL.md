---
name: hardening-shesha-app
description: Scans a Shesha application repository for security misconfigurations that are fixable in the application itself (not the framework) and applies safe, minimal fixes. Current checks are over-long JWT token lifetime, token blacklist not wired into JwtBearer OnTokenValidated (so sign-out does not revoke tokens), failed-login lockout disabled or weakened, and a Hangfire dashboard guarded by the starter's app-level "admin" filter instead of the framework's UseSheshaHangfireDashboard() (applied only on Shesha versions that ship it; otherwise it warns the user to upgrade and re-run). It is pluggable, so new checks drop into scripts/checks/. Use when the user asks to harden, secure or fix security settings in a Shesha app, to remediate audit findings about token expiry, sign-out, logout, token revocation, blacklisting, account lockout or the Hangfire dashboard, or to add a new application-level security check.
---

# Hardening a Shesha application

A scanner and fixer for security settings owned by the **application repository**: the
`{Project}WebCoreModule`, the Web.Host `AuthConfigurer`, `Startup`, appsettings and module
setting defaults. It is not for framework defects. Those go to shesha-io/shesha-framework issues.
It works on any Shesha repo, and detects the backend layout and `SheshaVersion` itself.

Run everything from the target repository's root. `$SKILL` is this skill's base directory (`<skill-dir>`, the path Claude Code
reports when the skill loads).

## Workflow

1. **Scan** (read-only):
   ```bash
   python $SKILL/scripts/harden.py scan --repo . --json hardening-report.json
   ```
   Optional live checks read the effective settings from a running backend. They never write:
   ```bash
   SHESHA_ADMIN_PASSWORD=... python $SKILL/scripts/harden.py scan --base-url http://localhost:21021 --username admin
   ```
   Never put the password on the command line unless the user insists. Use the environment variable.

2. **Report** to the user: each FAIL/WARN/MANUAL with its location and a one-line *why* from
   `references/checks.md`, plus which items are auto-fixable. Check the report for false
   positives before presenting it. Relay notes as well (e.g. whether the front end refreshes
   tokens, which decides whether a short lifetime is disruptive).

3. **Preview fixes.** A dry run is the default. Checks run **one at a time, in order**, and
   each sees the changes the earlier ones would make. It prints unified diffs, a simulated re-scan
   and the final report:
   ```bash
   python $SKILL/scripts/harden.py fix --only token-lifetime,token-blacklist
   ```
   Tune a fix with `--set <check>.<option>=<value>`, e.g. `--set token-lifetime.minutes=60`.
   `harden.py list` shows every option.

4. **Apply only after the user approves the diff.** Every check that changes code gets **its own
   commit**, holding only that check's change:
   ```bash
   git switch -c harden/<yymmdd>      # if on the default branch: the script refuses to commit there
   python $SKILL/scripts/harden.py fix --only <ids> --apply --commit --trailer "<attribution line>"
   ```
   - Pass your commit attribution line (e.g. `Co-Authored-By: ...`) as `--trailer`, if you have one.
   - The run refuses to start if anything is already staged. Ask the user to commit or unstage it;
     never stash or reset their work yourself.
   - The user's own uncommitted edits are never committed. If a file the check edits already had
     uncommitted changes, only the check's change is committed and theirs stay unstaged. If the two
     touch adjacent lines, the fix is applied but left **uncommitted**. The report says so; tell the user.
   - Commit hooks run normally. If one rejects a commit, that check's fix stays uncommitted in the
     working tree and the report says why.
   - Without `--commit`, `--apply` writes the files and commits nothing.

   Some fixes are gated on the framework version. If a check prints
   `WARNING - not applied: ...` (e.g. `hangfire-dashboard` on a Shesha version without
   `UseSheshaHangfireDashboard`), nothing was changed for it. Tell the user plainly that the issue is
   still open and that they need to upgrade Shesha (or run `dotnet restore`, if it says so) and
   **run this skill again**. Relay the interim mitigation from that check's *Manual fix*.

5. **Handle MANUAL items** by following that check's *Manual fix* in `references/checks.md`.
   Never overwrite a custom handler, and never change live settings without explicit consent.
   Commit a manual fix separately, and only if the user asks.

6. **Verify.** Build the backend (`dotnet build` on the Web.Host project; Shesha projects use
   `TreatWarningsAsErrors`, so check that no new warnings point at the edited lines), re-run
   `scan`, and if a backend is running, do the check's *Verify* steps (e.g. sign-off then expect 401).
   If the build fails, fix it in a follow-up commit rather than rewriting the hardening commits.

7. **Present the final report.** Every `scan` and `fix` run ends with a table, one row per check
   performed, which is also written to `--json` under `report`:

   | Check | Gap found | Current state | Action taken |
   |---|---|---|---|
   | `hangfire-dashboard` | yes (FAIL) | FAIL: dashboard uses the app-level filter ... | not applied: needs a Shesha version with UseSheshaHangfireDashboard(); upgrade, then re-run |
   | `token-blacklist` | yes (FAIL) | resolved | fixed, committed 1a2b3c4: wire token blacklist into OnTokenValidated |
   | `user-lockout` | no | OK | none needed |

   End your reply with this table, covering every check that ran, not only the ones with gaps.
   Update the *Current state* column if step 6 changed anything (e.g. a build failure), and add
   one line under the table for anything the user must do next: upgrade and re-run, manual fixes,
   or uncommitted fixes.

Exit code: `0` means no FAIL, `1` means at least one FAIL (usable as a CI gate), `2` means a usage error.

## Check catalog

| Check id | Severity | What must be true | Auto-fix | Reference |
|---|---|---|---|---|
| `token-lifetime` | high | `TokenAuthConfiguration.Expiration` is at most a few hours (FAIL >24 h, WARN >8 h) | Literal becomes configurable `Authentication:JwtBearer:TokenLifetimeMinutes` (default 120); over-long appsettings values are rewritten | [checks.md](references/checks.md) section 1 |
| `token-blacklist` | high | JwtBearer `OnTokenValidated` calls `EnsureTokenIsNotBlacklistedAsync()`, so `SignOff` revokes the token. n/a before Shesha 0.43.19 and on 0.44.x | Adds the handler to `JwtBearerEvents` (or adds the Events block) plus the `using` | [checks.md](references/checks.md) section 2 |
| `user-lockout` | high | Lockout is not switched off or weakened in code (framework default: on, 5 attempts, 300 s); with `--base-url`, not off in the live settings | `WithDefaultValue(false)` becomes `true`; everything else is manual | [checks.md](references/checks.md) section 3 |
| `hangfire-dashboard` | high | `/hangfire` is mapped with the framework's `UseSheshaHangfireDashboard()` (validated token + `Pages.Hangfire`), not `UseHangfireDashboard` with the starter's app-level "admin" filter | Only if the restored Shesha.Scheduler has the extension (shesha-framework#5554): the call is replaced, the app filter file and its `using` are deleted. Otherwise it is **not applied**, with a warning to upgrade and run the skill again | [checks.md](references/checks.md) section 4 |

## Adding a check

Drop a module into `scripts/checks/`. It is discovered automatically. Then document it in
`references/checks.md`, add a row to the table above, and add fixture tests. The template, rules
and a list of candidate checks are in [references/adding-a-check.md](references/adding-a-check.md).
The test suite fails if a registered check is missing from either document:

```bash
python $SKILL/scripts/test_checks.py
```

## Layout

```
hardening-shesha-app/
├── SKILL.md
├── references/
│   ├── checks.md            # why / detection / fix / manual fix / verify, one section per check
│   └── adding-a-check.md    # check template, rules, candidate checks
└── scripts/
    ├── harden.py            # CLI: list | scan | fix [--apply [--commit]]; per-check runs + final report
    ├── gitops.py            # one commit per check, never including the user's own uncommitted edits
    ├── core.py              # Repo, Check base class, registry, Finding/Issue/Edit, text helpers
    ├── test_checks.py       # fixture tests for every check
    └── checks/              # one module per check, auto-discovered
        ├── token_lifetime.py
        ├── token_blacklist.py
        ├── user_lockout.py
        └── hangfire_dashboard.py
```

## Principles

- **Dry run first.** Checks return edits; the runner writes them only with `--apply`.
- **One check, one commit.** With `--commit`, each check's change is reviewable and revertable on its own.
- **Recognise, or leave to a human.** An unfamiliar code shape is MANUAL, never a guess.
- **Look for the bad thing, not the missing good thing,** where the framework has a safe
  default. For example, lockout is on unless something turns it off.
- **Version-aware.** Framework capabilities are confirmed from the restored NuGet assembly
  (`~/.nuget/packages/...`) before falling back to a version table. A fix that needs a newer
  framework is never applied early: the check still reports the problem and says to upgrade and re-run.
- **Minimal diffs.** Keep line endings, BOM, indentation and comments; change the fewest characters possible.
