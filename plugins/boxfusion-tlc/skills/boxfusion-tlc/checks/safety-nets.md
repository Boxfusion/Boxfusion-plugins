# Safety-net checks (DevOps engineer)

These are the tools that catch mistakes before users do — tests, CI, dependency scanners, secret scanners, lock files. Graduates often don't know they exist, or that they are broken. Explain each briefly in the report.

**This file obeys `references/operating-standard.md`.** Every row is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists. IDs are `SN-X@<anchor>` (operating-standard §3) — **never** `SN-X-1/-2`; multiplicity is carried by the anchor.

**The tool IS the instrument — do not infer from version strings.** For the three tool-backed rows (`dotnet list package --vulnerable`, `npm audit`, `gitleaks`) the authoritative verdict is the tool's own output against a real advisory/pattern database. A present tool that runs = **VERIFIED-ARTEFACT**. **A tool's ABSENCE is a first-class fixed `NOT-ASSESSED(no-<tool>)` anchor** (never "clean", never a silent pass, never a weaker-instrument substitution that keeps the strong level — a seam-grep standing in for gitleaks is a `CODE-ONLY` spot-check, not a secret scan). Scanner and compile results are `VERIFIED-ARTEFACT`, never `REPRODUCED`.

**Pins (from the manifest, operating-standard §1):** `$SHA` = `$(SheshaVersion)`; tool presence from `manifest.capabilities.tools{dotnet,npm,gitleaks}`; `private_nuget_feed`/`private_npm_feed` presence; `repo.tree_state` (for the zero-commit history nuance).

## Capability-gating table (operating-standard §1 — absent capability ⇒ first-class NOT-ASSESSED, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` |
|---|---|
| `dotnet` | SN-VULN NuGet dimension → `SN-VULN@scanner:nuget` `NOT-ASSESSED(no-dotnet)`; SN-STALE `--outdated/--deprecated` → `NOT-ASSESSED(no-dotnet)` |
| `npm` | SN-VULN per-front-end npm dimension → `SN-VULN@scanner:npm` `NOT-ASSESSED(no-npm)` |
| `private_nuget_feed` (restore fails for module projects) | the unrestored projects' SN-VULN NuGet dimension → `SN-VULN@scanner:nuget:modules` `NOT-ASSESSED(no-private-feed)`; the restored projects stand at VERIFIED-ARTEFACT (partial result, both recorded) |
| `gitleaks` | SN-SCAN tree + history scan → `SN-SCAN@scanner:gitleaks` `NOT-ASSESSED(no-gitleaks)`; the SEC-E seam-grep stands as a stated CODE-ONLY spot-check |
| git history (`tree_state=zero-commit`) | SN-SCAN history dimension + SN-DBDUMP `git ls-files` dimension → `NOT-ASSESSED(zero-commit-repo)`; the working-tree scans still run |

## Determinism pins (apply exactly)
- **The capability-gated NOT-ASSESSED anchors are MANDATORY fixed strings — every operator emits every applicable one, always:** `SN-VULN@scanner:nuget`, `SN-VULN@scanner:npm`, `SN-VULN@scanner:nuget:modules`, `SN-SCAN@scanner:gitleaks`. Fixed so two runs' NOT-ASSESSED sets match exactly (operating-standard §8). Info/NOT-ASSESSED records never enter fix-order (§6).
- **SN-VULN severity is the advisory band the tool reports, not the §5 grid.** The GHSA/NVD database already encodes impact × exploitability, so the finding's severity = the **max advisory band present** in the tool output: `critical→Critical, high→High, moderate→Medium, low→Low`. One `SN-VULN` finding per ecosystem/front-end (`SN-VULN@dep:npm:<app>`, `SN-VULN@dep:nuget:<scope>`), body carrying the count-by-band and the direct-vs-transitive split — not one finding per CVE (that set drifts as the advisory DB updates between runs; the band + counts at the pinned commit is the stable artefact). impact_class is recorded as `advisory-reported`.
- **SN-SECRETS and SN-DBDUMP delegate to SEC-E.** Committed secrets and committed DB dumps are SEC-E's findings (`SEC-E@<path>`), with SEC-E's `RC-committed-secrets` root_cause and severity. Safety-nets runs the **detection scan** and emits the SEC-E-shaped anchor, but does not create a second competing record — overlap priority: SEC-E owns the committed-secret/dump severity. SN keeps the **CI-control** gap (no gitleaks step, no push-protection) as its own `SN-SCAN` finding.
- **SN-DBDUMP uses the working-tree scan AND `git ls-files` — never `git ls-files` alone.** On a fresh/zero-commit repo nothing is tracked yet, so `git ls-files` is empty and a dump in the root is missed; the working-tree `find`/`ls` catches it. History dimension → `NOT-ASSESSED(zero-commit-repo)` when there are no commits.
- **root_cause is an enumerated `RC-ops-*` id** (this file's table; must be merged into operating-standard §3), except the SEC-E-delegated rows which carry `RC-committed-secrets`. `fix_order_rank` = f({severity, root_cause, anchor}).

## Fixed severity-inputs per row (operating-standard §5 — impact_class + data_sensitivity FIXED; reachability from the manifest). Most safety-net gaps are process/maintainability defects at `local_only`.
| Row (id) | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| SN-TEST (tests exist/run) | maintainability | none | local_only → Low |
| SN-E2E (end-to-end tests) | maintainability | none | local_only → Low |
| SN-LINT (lint/type-check) | maintainability | none | local_only → Low |
| SN-CI (PR gate) | maintainability | none | local_only → Low |
| SN-REVIEW (code review/branch policy) | maintainability | none | local_only → Low |
| SN-AUTHINV (auth-inventory test) | maintainability | none | local_only → Low (the live risk is SEC-C) |
| SN-VULN (CVEs) | advisory-reported | none | **advisory max band** (Critical..Low) |
| SN-STALE in-support runtime | maintainability | none | local_only → Low |
| SN-STALE **EOL/past-support** runtime | maintainability | none | local_only → Low **(stated-Medium if past the support end-date)** |
| SN-FWK (framework minor behind) | maintainability | none | local_only → Low |
| SN-LOCK (lock files) | maintainability | none | local_only → Low |
| SN-MIGRATE (clean-build migrations) | maintainability | none | local_only → Low |
| SN-SCAN (no CI scanner step) | maintainability | none | local_only → Low |
| SN-SECRETS / SN-DBDUMP | → **SEC-E** (RC-committed-secrets, SEC-E severity) |

`root_cause` map: SN-TEST/E2E/LINT/CI/REVIEW/AUTHINV/SN-SCAN(control) → `RC-ops-ci-gate`; SN-VULN/STALE/FWK/LOCK → `RC-ops-dependency-hygiene`; SN-MIGRATE → `RC-ops-build-reproducibility`; SN-SECRETS/SN-DBDUMP → `RC-committed-secrets` (delegated to SEC-E).

---

## SN-VULN: Dependency vulnerabilities (CVEs). **impact_class=advisory-reported, RC-ops-dependency-hygiene.** Run the tools — they are authoritative.
- **INPUT:** NuGet — `dotnet list package --vulnerable --include-transitive` (GHSA/NVD-backed). npm — `npm audit --omit=dev` in **each** front end. Record the raw tool output.
- **PREDICATE:** the tool reports ≥1 vulnerability (minus triaged FPs) for an ecosystem/front-end → one finding per ecosystem/front-end. **If a front-end/ecosystem's scanner is absent → the fixed `NOT-ASSESSED(no-<tool>)` anchor.** **If NuGet restore fails for some projects (private feed unreachable) → the restored projects are VERIFIED-ARTEFACT and the unrestored module projects are `SN-VULN@scanner:nuget:modules` `NOT-ASSESSED(no-private-feed)` — a partial result, both recorded, flagged for re-run.**
- **VERDICT/ANCHOR:** `SN-VULN@dep:npm:<app>` / `SN-VULN@dep:nuget:<scope>` (body: count-by-band, direct vs transitive, each direct package with fix-available/no-fix). Watch the smell where a runtime `package.json` lists the whole `npm` CLI as a dependency (`"npm": "^..."`), dragging its vulnerable tree in — call it out and recommend removal.
- **EVIDENCE:** tool ran → **VERIFIED-ARTEFACT**; tool/feed absent → NOT-ASSESSED(no-<tool> / no-private-feed).
- **REMEDIATION `PLAN-SN-VULN`:** `npm audit fix` / bump the fixable set; schedule the framework/runtime upgrade for no-fix critical/high; remove any `npm`-as-runtime-dependency; **Dependabot/Renovate as the standing control**; re-run the NuGet scan where the private feed is reachable before sign-off.
- **REGRESSION TEST:** `Dependencies_NoKnownVulnerabilities_CI` (the scanner wired as a PR gate).
- **SEVERITY:** the **advisory max band** reported (critical→Critical … low→Low); NOT-ASSESSED records → Info.

## SN-STALE: Dependency staleness / EOL runtime. **impact_class=maintainability, RC-ops-dependency-hygiene.** A different axis from CVEs — a package can be CVE-free but abandoned or past end-of-support.
- **INPUT:** `dotnet list package --outdated --deprecated`; the `TargetFramework`/`global.json` vs the .NET support lifecycle; Shesha/ABP minor vs current. (.NET 8 is LTS, in support to **Nov 2026**; .NET 6/7 are EOL.)
- **PREDICATE:** a runtime is **past its support end-date** (EOL) OR the framework minor is materially behind (carrying in-version defects) OR `--deprecated` reports a package → one finding per axis.
- **VERDICT/ANCHOR:** `SN-STALE@runtime:<tfm>` / `SN-STALE@framework:shesha-<ver>` / `SN-STALE@dep:<name>:deprecated`. (Feed-dependent `--outdated` → `NOT-ASSESSED(no-private-feed)` if the feed is unreachable.)
- **EVIDENCE:** version/date comparison → CODE-ONLY; tool output → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-STALE`:** plan the next-LTS move while in support; schedule the Shesha/ABP minor upgrade (note upgrade blockers); add Dependabot/Renovate.
- **REGRESSION TEST:** `Dependencies_RuntimeInSupportAndFrameworkCurrent_CI`.
- **SEVERITY:** maintainability × local_only → **Low**; **stated-Medium when the runtime is past its support end-date.**

## SN-FWK: Framework version. **impact_class=maintainability, RC-ops-dependency-hygiene.**
- **INPUT:** the Shesha version (`$SHA`) vs current releases; note upstream fixes/security patches available and upgrade blockers.
- **PREDICATE:** `$SHA` is ≥1 minor behind current → finding (fixes/security patches available upstream, e.g. the in-version SEC-I defect).
- **VERDICT/ANCHOR:** `SN-FWK@framework:shesha-$SHA`.
- **EVIDENCE:** CODE-ONLY (version comparison).
- **REMEDIATION `PLAN-SN-FWK`:** schedule the upgrade; defer the mechanics to `upgrade-shesha-stack`; route in-version framework defects to the Shesha team report.
- **REGRESSION TEST:** covered by `Dependencies_RuntimeInSupportAndFrameworkCurrent_CI`.
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-LOCK: Dependency lock files committed. **impact_class=maintainability, RC-ops-dependency-hygiene.**
- **INPUT:** backend `packages.lock.json` + `RestorePackagesWithLockFile` in `Directory.Build.props`/csproj; `package-lock.json`/`yarn.lock` per front end; whether CI uses a frozen install (`npm ci`) not `npm install`.
- **PREDICATE:** a lock file is missing for an ecosystem OR CI uses `npm install` rather than `npm ci` (lock present but not enforced) → one finding per gap.
- **VERDICT/ANCHOR:** `SN-LOCK@lockfile:nuget:missing` / `SN-LOCK@lockfile:<app>:not-enforced`. (A pipeline that branches on a `lockFileExists` variable while never committing one is the anticipated-but-absent anti-pattern — record it.)
- **EVIDENCE:** working-tree + pipeline read → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-LOCK`:** enable `RestorePackagesWithLockFile` + commit `packages.lock.json`; switch CI to `npm ci`.
- **REGRESSION TEST:** `Build_LockFilesCommittedAndCiUsesFrozenInstall_Test`.
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-TEST: Unit and integration tests exist and run. **impact_class=maintainability, RC-ops-ci-gate.**
- **INPUT:** find test projects (`*.Tests*.csproj`, `**/*.test.*`, `**/*.spec.*`), count tests, run them; note missing adapters or broken start-up configuration.
- **PREDICATE:** a tier has **no** tests OR the suite **cannot start** (see common failure reasons below) → one finding per tier/project.
- **VERDICT/ANCHOR:** `SN-TEST@project:<project-name>` (or `SN-TEST@tier:backend|frontend:none`).
- **EVIDENCE:** ran/failed-to-start → VERIFIED-ARTEFACT; count-only read → CODE-ONLY.
- **REMEDIATION `PLAN-SN-TEST`:** fix the start-up blocker (see below); add tests to the empty tier; bring coverage to standard (this precedes the specialist checks, per the skill flow).
- **REGRESSION TEST:** the test suite itself, wired into the PR gate (SN-CI).
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-E2E: End-to-end tests. **impact_class=maintainability, RC-ops-ci-gate.**
- **INPUT:** e2e plans/specs and when they last passed.
- **PREDICATE:** no e2e suite, OR it has not passed recently → finding.
- **VERDICT/ANCHOR:** `SN-E2E@suite:none` / `SN-E2E@suite:stale`.
- **EVIDENCE:** VERIFIED-ARTEFACT (presence + last-run) / CODE-ONLY.
- **REMEDIATION `PLAN-SN-E2E`:** author/repair the critical-journey e2e suite; run it in CI.
- **REGRESSION TEST:** the e2e suite in CI.
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-LINT: Linting and type-checking work. **impact_class=maintainability, RC-ops-ci-gate.**
- **INPUT:** run the lint + type-check commands; note missing plugins and the baseline error count.
- **PREDICATE:** lint/type-check **cannot run** (missing plugin) OR is absent from CI → finding per tier.
- **VERDICT/ANCHOR:** `SN-LINT@tier:<frontend|backend>:broken|absent`.
- **EVIDENCE:** ran/failed → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-LINT`:** restore the missing plugin; add lint + type-check to the PR gate.
- **REGRESSION TEST:** lint/type-check step in CI.
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-CI: CI pipeline gates PRs. **impact_class=maintainability, RC-ops-ci-gate.**
- **INPUT:** read the pipeline files (e.g. Azure DevOps `*.yaml`). For each, confirm a `pr:`/`trigger:` on main AND that it runs build + **test** + **lint** (+ scan). A pipeline that runs `dotnet test` but has no `pr:`/`trigger:` is **not** a PR gate.
- **PREDICATE:** the PR-triggered pipeline omits `dotnet test` OR lint OR a scanner step, OR a test pipeline exists but isn't PR-triggered → one finding per missing gate.
- **VERDICT/ANCHOR:** `SN-CI@pipeline:<file>:no-test-gate` / `:no-lint` / `:no-scan` / `:not-pr-triggered`.
- **EVIDENCE:** pipeline-file read → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-CI`:** add `dotnet test` + lint to the PR gate; wire the auth-inventory test (SN-AUTHINV) and the gitleaks step (SN-SCAN); re-enable any commented-out analyser (e.g. backend SonarCloud); prefer `npm ci`.
- **REGRESSION TEST:** `Ci_PrGateRunsBuildTestLintScan_Test` (a meta-assertion over the pipeline definition).
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-REVIEW: Code review and branch policies. **impact_class=maintainability, RC-ops-ci-gate.**
- **INPUT:** do PRs get reviewed? are there branch policies? is an AI reviewer configured (e.g. `.coderabbit.yaml`)?
- **PREDICATE:** no required reviewer / no branch policy on main → finding. (A present review workflow is "checked and fine".)
- **VERDICT/ANCHOR:** `SN-REVIEW@branch-policy:main:absent`.
- **EVIDENCE:** repo/pipeline config → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-REVIEW`:** require ≥1 reviewer + a branch policy on main.
- **REGRESSION TEST:** branch-policy assertion (platform config review).
- **SEVERITY:** maintainability × local_only → **Low**.

## SN-AUTHINV: Authorisation-inventory test in CI. **impact_class=maintainability, RC-ops-ci-gate.** (The live risk is `checks/security.md` SEC-C.)
- **INPUT:** is there a CI test listing every endpoint and failing on Inherited / "any authenticated" ones not on an allow-list?
- **PREDICATE:** no such test in CI → finding.
- **VERDICT/ANCHOR:** `SN-AUTHINV@ci:auth-inventory:absent`.
- **EVIDENCE:** pipeline/test read → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-AUTHINV`:** add the `AuthorizationInventory_NoInheritedOrAnyAuthenticated_Test` (SEC-C's named regression test) to CI so new endpoints can't ship open.
- **REGRESSION TEST:** `AuthorizationInventory_NoInheritedOrAnyAuthenticated_Test` (shared with SEC-C).
- **SEVERITY:** maintainability × local_only → **Low** (the reachable-endpoint risk itself is scored under SEC-C).

## SN-SCAN: Secret scanning (run it now, and gate PRs). **impact_class=maintainability (CI-control) / delegates to SEC-E (findings), RC-ops-ci-gate.**
- **INPUT:** run **gitleaks** over the working tree (`gitleaks detect --source . --no-git`) AND git history (`gitleaks detect --source .`); check the PR pipeline for a scanner step (gitleaks/trufflehog) + GitHub push protection.
- **PREDICATE:** (a) gitleaks reports a finding → the secret itself is a **SEC-E** finding (`SEC-E@<path>`, RC-committed-secrets); (b) **gitleaks is absent → the fixed `SN-SCAN@scanner:gitleaks` `NOT-ASSESSED(no-gitleaks)` record** (the SEC-E seam-grep stands as a CODE-ONLY spot-check, never "clean"); (c) no scanner step / no push-protection in the pipeline → `SN-SCAN@ci:secret-scan:absent` (this file's own CI-control finding).
- **VERDICT/ANCHOR:** `SN-SCAN@scanner:gitleaks` (NOT-ASSESSED when absent) + `SN-SCAN@ci:secret-scan:absent` (control gap); actual secrets → SEC-E.
- **EVIDENCE:** gitleaks ran → VERIFIED-ARTEFACT; absent → NOT-ASSESSED(no-gitleaks); pipeline read → VERIFIED-ARTEFACT.
- **REMEDIATION `PLAN-SN-SCAN`:** add a gitleaks PR step + full-history scan + GitHub push-protection (a real scanner — 180+ provider patterns, history coverage — beats a grep).
- **REGRESSION TEST:** `SecretScan_GitleaksCleanTreeAndHistory_CI` (shared with SEC-E).
- **SEVERITY:** CI-control gap maintainability × local_only → **Low**; NOT-ASSESSED(no-gitleaks) → Info; committed-secret severity → SEC-E.

## SN-SECRETS: Secrets not in the repo. **→ `checks/security.md` SEC-E (RC-committed-secrets).**
- **INPUT/PREDICATE/ANCHOR:** detection is SEC-E's (seam grep + gitleaks over `appsettings*.json`, module `.WithDefaultValue(` literals, CI/compose/helm, `NEXT_PUBLIC_*`). A committed JWT signing key, shared QA credentials, etc. are `SEC-E@<path>` findings. Safety-nets runs the scan and surfaces them under SEC-E — no competing SN record.
- **SEVERITY:** per SEC-E.

## SN-DBDUMP: No committed database dump. **→ `checks/security.md` SEC-E (SEC-E owns committed dumps, RC-committed-secrets).**
- **INPUT:** scan the **working tree** (`find`/`ls` for `*.bacpac` / `*.bak` / `*.backup` / `*.dump`) **AND** `git ls-files` for the same patterns. Use both — on a zero-commit repo `git ls-files` is empty and a dump in the root is missed by it alone.
- **PREDICATE:** a DB dump exists in the working tree or is tracked → a `SEC-E@<repo-relative-path>` finding (no suffix, per SEC-E's R8 pin, e.g. `SEC-E@hcm.bacpac`). Two DBMS dumps signal ad-hoc seeding. History dimension → `NOT-ASSESSED(zero-commit-repo)` when no commits.
- **VERDICT/ANCHOR:** `SEC-E@<path>` (SEC-E record); SN surfaces it, does not duplicate it.
- **EVIDENCE:** working-tree/`git ls-files` scan → VERIFIED-ARTEFACT.
- **REMEDIATION:** `PLAN-SEC-E` — remove from repo **and history**, move to a secure store, build from migrations.
- **REGRESSION TEST:** `SecretScan_GitleaksCleanTreeAndHistory_CI` + a repo guard rejecting dump extensions.
- **SEVERITY:** per SEC-E (committed dump with potential PII → secret_exposure/popia_special → High/Critical).

## SN-MIGRATE: Migrations are reproducible. **impact_class=maintainability, RC-ops-build-reproducibility.**
- **INPUT:** confirm a clean database builds from migrations (FluentMigrator `M<UTC>.cs` across modules); reference data is in migrations/seeds, not set by hand.
- **PREDICATE:** a clean build from migrations fails OR reference data is hand-seeded (hand-SQL anti-pattern) OR committed DB dumps undermine the clean-build path → finding.
- **VERDICT/ANCHOR:** `SN-MIGRATE@migrations:clean-build` / `SN-MIGRATE@seed:hand-sql`.
- **EVIDENCE:** clean-build run → VERIFIED-ARTEFACT; mechanism-present read → CODE-ONLY.
- **REMEDIATION `PLAN-SN-MIGRATE`:** put reference data in migrations/seeds; remove committed dumps (SN-DBDUMP/SEC-E); rehearse migrations on a production-sized copy (ties OPS-G).
- **REGRESSION TEST:** `Migrations_BuildCleanDatabase_Test`.
- **SEVERITY:** maintainability × local_only → **Low**.

---

**Common reasons existing tests "don't work" (diagnose before calling a tier empty):**
- configuration packages imported at test start-up need modules the test module doesn't load (e.g. a messaging module), so every test fails at start-up;
- a module that starts its own message bus at start-up blocks database-backed tests for the whole module;
- a stale `node_modules` not matching the lock file (run `npm ci`); some commit hooks fail in a fresh worktree without it;
- an expired private-npm-feed token;
- assertions too loose to fail (`checks/code.md` CODE-I).

**Framework-defect candidates** (→ `templates/shesha-team-report.md`, only after reproduced): an in-version Shesha defect surfaced by SN-FWK/SN-STALE is never a finding against the system's own developers.
