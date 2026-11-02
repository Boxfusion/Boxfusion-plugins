# Security checks

Test as a **logged-in user with the least privilege that is realistic** and as an anonymous caller. Synthetic users and records only. Presence-only for secrets and personal data (never a value; presence + length band + `file:line`/`#symbol` only).

**This file obeys `references/operating-standard.md`.** Every check is a decision procedure: **INPUT → PREDICATE (boolean) → VERDICT → ANCHOR**, then **REMEDIATION (plan_id + template) → REGRESSION TEST → SEVERITY INPUTS**. A finding is raised **iff** the predicate is true and an anchor exists. IDs are `SEC-X@<anchor>` (operating-standard §3) — **never** `SEC-X-1/-2`; multiplicity is carried by the anchor. Severity is scored intrinsically from the operating-standard §5 table (evidence level is a separate axis, not a severity input).

**Run SEC-I first on every system.** A hit is an urgent stop.

**Pins (from the manifest, operating-standard §1):** `$SHA` = `$(SheshaVersion)` from `backend/Directory.Build.props`; `$DLL` = the `Shesha.Application/$SHA` path resolved from `Web.Host/obj/project.assets.json` (every decompile targets this exact path). `$BASE` = the backend URL when `backend_running`.

## Capability-gating table (operating-standard §1 — absent capability ⇒ first-class NOT-ASSESSED, never a silent pass)
| Capability absent | Dimensions that become `NOT-ASSESSED(reason)` |
|---|---|
| `backend_running` | live-probe dimension of SEC-I/D/O/F → `NOT-ASSESSED(no-backend)`; the static/decompile predicate still runs at CODE-ONLY/VERIFIED-ARTEFACT |
| `low_priv_account` | authenticated-reachability of SEC-A/B/C/K/L/M/N → `NOT-ASSESSED(no-low-priv-user)`; anonymous/static evidence stands, not upgraded past VERIFIED-ARTEFACT/CODE-ONLY |
| `gitleaks` | SEC-E history/entropy recall → `NOT-ASSESSED(no-secret-scanner)` (a named finding line); seam-grep findings stand at VERIFIED-ARTEFACT |
| git history (zero-commit) | SEC-E history dimension → `NOT-ASSESSED(zero-commit-repo)`; working-tree scan still runs |
| `app_insights` | SEC-H telemetry-PII dimension → `NOT-ASSESSED(no-telemetry)` |
| `sec_analyzer` / backend buildable (no `Compilation`) | SEC-A and SEC-H H1 (Roslyn-analyzer instrument) → fixed `SEC-A@analyzer` / `SEC-H@analyzer` `NOT-ASSESSED(no-build)`; when present they are `VERIFIED-ARTEFACT` and enter the acceptance diff |

## Determinism pins (R2 acceptance-test resolutions — apply exactly; these remove observed cross-operator divergences)
- **Closed set includes the handovers.** `--security-only` always raises CODE-F-1 (client-forgeable `sha-position-appointment-id` header; anchor `adminportal/src/middleware.ts#middleware`, root_cause `RC-browser-trusted-flow`) and CODE-G-1 (inverse permission-checker; anchor `...#HcmPermissionChecker.IsGrantedAsync`, root_cause `RC-no-authz-model`) as their own findings — never folded into SEC-C narrative.
- **SEC-C anchors + evidence (fixed):** `SEC-C@sln:authorize-ratio=<A>/<N>` is **VERIFIED-ARTEFACT** (a grep-count artifact). `SEC-C@sln:DefaultEndpointAccess` is **live-read only** → `NOT-ASSESSED(no-backend)` in `--static` (do NOT decompile a default whose type location isn't pinned — it diverged: one operator found it, one didn't; the root finding rests on the authorize-ratio both find). root_cause `RC-no-authz-model`.
- **SEC-E scope + casing (fixed):** committed credential literals in **any tracked text file** are in scope, incl. `CLAUDE.md` and `test-plans/*` → each `SEC-E@<path>:credentials`, severity by reachability (shared QA creds in a public repo = secret_exposure × anonymous unless confirmed not reused → then low). The JWT key anchor is `#key:Authentication.JwtBearer.SecurityKey` **verbatim from the file** (never lowercased). root_cause `RC-committed-secrets`.
- **SEC-D (fixed):** each dev endpoint whose registration is visible in `Startup` is its **own CODE-ONLY finding** — `SEC-D@http:GET /elmah`, `SEC-D@http:GET /swagger`, `SEC-D@http:GET /ui/playground` — PLUS one fixed `SEC-D@probe` record `NOT-ASSESSED(no-backend)` for live reachability. Never fold elmah into the probe record. root_cause `RC-starter-hardening`.
- **SEC-M (fixed):** enumerate **every** `*ImportAppServiceBase` (grep `: *\w*ImportAppServiceBase`); anchor at `#<Type>.StartImportAsync` (method, not type). root_cause `RC-input-integrity`.
- **SEC-N (fixed):** the no-allow-list outbound-target finding is **CODE-ONLY** (statically visible), anchored at the method (`#<Type>.DoExecuteAsync`); the separate "is the setting non-admin-writable" question is a `NOT-ASSESSED(no-low-priv-user)` note, not the finding's level. root_cause `RC-input-integrity`.
- **SEC-A enumeration (fixed, mechanical):** candidate set = `grep -rn 'Task<[^>]*> \w\+Async(.*\b\(Guid\|Guid?\) [a-z]*\(Person\|Profile\|Owner\|User\|Employee\|Appointment\)Id'` over app-service/controller files, **minus** audit fields and admin assign-to-X writes. For each candidate, PREDICATE = the id param flows into the read/scope decision AND no `AbpSession`/`GetLoggedInPersonAsync`/`CurrentUser` cross-check in the body. Raise `SEC-A@<path>#<Type>.<Member>` for **every** candidate that satisfies it (both the delegation-appointment and the cycle-items methods qualify — do not pick one). root_cause `RC-no-authz-model`.
- **SEC-H enumeration (fixed, mechanical):** candidate set = `grep -rn 'Log\(Info\|Debug\|Warn\|Error\)\|_logger\.\|_log\.' ` lines whose interpolation/concatenation includes a PII property name from the POPIA list (`IdentityNumber|PersalNo|FullName|DateOfBirth|leaveReason|...`). Raise one `SEC-H@<path>#<Type>.<Member>` per such site (both operators must return the same set — there were 4). telemetry dimension = fixed `SEC-H@telemetry` `NOT-ASSESSED(no-telemetry)`. root_cause `RC-pii-handling`.
- **SEC-K test-endpoint predicate (fixed):** a method is a SEC-K test/debug endpoint **iff** its name or an enclosing `#region`/comment matches `/simulate|generate-?test|send-?test|#region Debug|testing purposes|for testing only/i` AND it is on a `ControllerBase`/app-service with no `[AbpAuthorize]`. A production generator without such a marker (e.g. `GenerateInputTransactionsForApplicationAsync`) is **not** a test-endpoint finding — it is assessed under the normal SEC-C/SEC-K authz predicates only. This removes the disputed inclusion.
- **root_cause is an enumerated id** from `references/operating-standard.md` §3 vocabulary — never free text. `fix_order_rank` is computed from {severity, root_cause, anchor}, so it matches across runs.

## Determinism pins — R4 acceptance resolutions (second pass; close the C-vs-D divergences)
- **SEC-A is now DETERMINISTIC via the Roslyn analyzer (`analyzers/BoxfusionTlc.SecAnalyzers`, DiagnosticAnalyzer `SEC_A`) — quarantine RETIRED.** The grep was broken (can't match `Task`/nested generics, PascalCase-vs-camelCase param names) so operators read signatures by eye and diverged. The analyzer replaces it: over the semantic model it raises `SEC-A@<path>#<Type>.<Member>` for every **public app-service/controller** method (base chain `ApplicationService`/`ControllerBase`/`AbpController`, or name `*AppService`/`*Controller` — NOT internal `DomainService` managers) that has a `Guid`/`Guid?` actor-id parameter (name ends `Id` and contains one of person/profile/owner/user/employee/appointment/farmer/delegat, minus `creator/lastModifier/deleter`), where that parameter **flows into a read/scope decision** (argument to a repository/LINQ query, or an `==`/`!=` filter against an entity `…Id`, excluding `Guid.Empty`/`null`/`default` guards) AND the body has **no** `AbpSession`/`GetLoggedInPersonAsync`/`GetCurrentPersonAsync`/`CurrentUser` cross-check. Findings carry `non_deterministic:false` and enter the acceptance diff. Two runs on the same commit are byte-identical (proven on pd-Hcm `7fc13b84`: 8 app-service sites incl. both the delegation-appointment `CreateDelegationAppointmentAsync` and the cycle-items `GetEmployeePerformanceItemsAsync`). If the backend cannot be built (no `Compilation`), the analyzer emits the fixed `SEC-A@analyzer` `NOT-ASSESSED(no-build)` record — never a silent pass.
- **SEC-E credentials = ONE aggregate finding, not per-file.** Committed shared/QA credential literals are a single `SEC-E@credentials:shared-qa` record (VERIFIED-ARTEFACT) whose body carries the matched-file **count** and the two authoritative stores (`CLAUDE.md`, `test-plans/.../shared/`), not N per-file duplicates. (C emitted 68, D emitted 2 — both wrong shapes; this is the fixed shape.) The JWT key and each DB dump stay their own findings. Severity: shared QA creds, confirmed not reused in prod ⇒ `secret_exposure × local_only` → Low; unknown reuse ⇒ any_authenticated → High.
- **SEC-B enumeration (fixed grep, so it always fires).** Candidate set = `rg -n ": *ControllerBase|: *AbpController" --type cs` ∩ methods whose route/params take an id/natural-key and return a document/stream (PDF/scoresheet/report download). The 11 pd-Hcm PDF/scoresheet controllers are the reference set. Raise `SEC-B@<path>#<Controller>.<Method>` for every one whose list counterpart applies a scope symbol the by-id method does not. (D missed all 11 → the predicate must be run as this grep, not by judgement.)
- **SEC-K closed enumeration + sub-predicate priority (fixes 11-vs-5 and impact_class).** Run ALL five sub-predicate greps over BOTH `PersalInputFileController` and `PmdsPersalInputFileController` AND the `*PersalAppService` literal-guard methods AND `CreateTransactionsAsync`. Each method is classified by a **priority-ordered first-match** rule (pins impact_class deterministically): (1) literal-guard → auth_bypass; (2) test-endpoint marker → auth_bypass; (3) http-get-mutation → data_integrity; (4) status-write → data_integrity. So `CompletePersalStep*` = literal-guard/auth_bypass/Critical; the `simulate/generate-test/send-test` endpoints = test-endpoint/auth_bypass/Critical; `CreateTransactionsAsync` = http-get-mutation/data_integrity/High. The full reference set on pd-Hcm is **11 code findings** (2 literal-guards + 8 test endpoints across both controllers + CreateTransactions).
- **SEC-H frozen POPIA token list (no `...`).** The value-interpolation grep uses exactly: `IdentityNumber|PersalNo|PersalNumber|FullName|DateOfBirth|leaveReason`. A site qualifies iff a PII token appears **inside a `$"…{…}…"` interpolation or string concat** (not a bare mention). Reachability for background jobs/imports (no HTTP actor) = `low_priv` by rule. This yields a fixed set at a given commit (the "4" parenthetical was wrong — the set is whatever this frozen grep returns; do not add tokens).
- **Empty-verdict + NOT-ASSESSED records: fixed severity token = `Info`, fixed evidence encoding.** `SEC-x@<vector>=none` and `SEC-x@none` records are `evidence_level=CODE-ONLY, severity=Info`; `NOT-ASSESSED(reason)` records are `severity=Info`. (C used `None`, D used `Info`/varied — pin to `Info` so SEC-G/SEC-J/SEC-F empty verdicts match. The normalizer treats `Info` and `None` as equal defensively, but author `Info`.)
- **Handover plan_id + impact_class pinned:** CODE-F-1 → `plan_id=PLAN-SEC-A`, impact_class=auth_bypass. CODE-G-1 → `plan_id=PLAN-SEC-C`, impact_class=auth_bypass, reachability=any_authenticated (NOT admin_only — it is the global checker) → Critical. CODE-G-3 (Hangfire `username=="admin"` filter) → `plan_id=PLAN-SEC-D`, impact_class=info_leak, reachability=admin_only → Low.
- **SEC-N enumeration (fixed):** every `*PersalSendInputFileJob#DoExecuteAsync` (outbound FTP from settings, no allow-list). Do NOT include `SendTestOutputFileAsync` under SEC-N (it is a SEC-K test-endpoint — avoid double-listing across checks; overlap priority: SEC-K wins for test endpoints).

## Determinism pins — R6 resolutions (third pass; severity-inputs + exact greps)
The R6 re-test converged all anchors but diverged on **severity-inputs** (same finding, different band) and a few **described-vs-exact greps**. Pin both.

**Fixed severity-inputs per check (impact_class + data_sensitivity are FIXED properties of the check, not per-finding judgement; reachability resolves from the gate).** Author these exactly so two operators compute the same band:
| Check | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| SEC-I | secret_exposure | secret | anonymous → Critical |
| SEC-C authorize-ratio | auth_bypass | popia_special | any_authenticated → Critical |
| SEC-E JWT key | auth_bypass | secret | any_authenticated → Critical |
| SEC-E DB dump | secret_exposure | popia_special | any_authenticated → Critical |
| SEC-E credentials:shared-qa | secret_exposure | none | any_authenticated → High |
| SEC-O CORS (O2) | auth_bypass | none | anonymous → Critical |
| SEC-O headers (O1/O4/O5) | info_leak | none | anonymous → Low |
| SEC-D dev endpoint | info_leak | none | anonymous → High |
| SEC-B **all** by-id PDF/scoresheet | data_exposure_pii | **pii_basic (do NOT special-case Z1 as popia_special)** | any_authenticated → High |
| SEC-K literal-guard / test-endpoint | auth_bypass | business | any_authenticated → Critical |
| SEC-K http-get-mutation | data_integrity | business | any_authenticated → High |
| SEC-H PII-in-logs | data_exposure_pii | pii_basic | low_priv → High |
| SEC-M upload | **dos** | none | any_authenticated → **Low** (fixed; not info_leak/data_integrity) |
| SEC-N settings-FTP | info_leak | none | low_priv → Low |
| SEC-L mass-assignment | data_integrity | popia_special | local_only (latent) → Medium |
| CODE-F-1 | auth_bypass | business | any_authenticated → Critical |
| CODE-G-1 | auth_bypass | business | any_authenticated → Critical |
| CODE-G-3 | info_leak | none | admin_only → Low |
Empty-verdict / NOT-ASSESSED records: severity `Info` (already pinned).

**Exact greps (replace described predicates; one command → one result):**
- **SEC-C denominator** = unique classes from `rg -No --type cs "class \w+AppService\b" backend/src | grep -vi "/obj/\|/bin/\|\.tests\?/" | sort -u | wc -l` (counts classes incl. plural-filename/multi-class files → one canonical N; pd-Hcm = pin the value this returns). Numerator A = same over classes carrying `[AbpAuthorize("`/`[SheshaAuthorize(`. Anchor `sln:authorize-ratio=A/N`.
- **SEC-D `/ui/playground`** raise IFF `rg -n "ui/playground|GraphQLPlayground|UseGraphQLPlayground|MapGraphQL" backend/src --type cs` matches (search ALL cs files — do NOT constrain to a `*/Startup*.cs` glob: the real file is `.../Web.Host/Startup/Startup.cs`, two levels deep, so a shallow glob silently misses it and two operators diverge). Decide by this exact recursive grep, not by belief.
- **SEC-E `scanner:gitleaks` is a MANDATORY fixed-anchor record** when gitleaks is absent — always emit `SEC-E@scanner:gitleaks` `NOT-ASSESSED(no-secret-scanner)` (one operator omitted it; it is non-optional like the other capability-gated records).
- **SEC-H sites** = `rg -n "\$\"[^\"]*\{[^}]*(IdentityNumber|PersalNo|PersalNumber|FullName|DateOfBirth|leaveReason)[^}]*\}" backend/src --type cs` (interpolated value only). Raise one finding per matching method; the set is whatever this exact command returns (do not add/remove by judgement).
- **SEC-L** = raise IFF `rg -n "CreateMap<\w*Dto, *\w+>|\.ReverseMap\(\)|\[AutoMap" backend/src --type cs` matches a DTO→entity exposing a protected field; else `SEC-L@none`. (Resolves E's EmployeeMappingProfile vs F's none — by the exact grep.)
- **SEC-G vector anchors use fixed names:** `xss|xxe|deserialization|open-redirect|hql|csv-injection|ldap|oscmd|ssti|redos` (e.g. `SEC-G@csv-injection=none`, never `csv-formula`). Emit the same fixed vector set every run.

## Determinism pins — R8 resolutions (final pass; the last two trivial classes)
The R8 re-test (operators G/H) matched on ~78/78 deterministic records except two trivial classes. Pin both:
- **DB-dump anchor has NO suffix:** `SEC-E@<repo-relative-path>` exactly (e.g. `SEC-E@hcm.bacpac`, `SEC-E@hcm-postgresql.backup`) — never a `:db-dump` or other suffix. One operator added `:db-dump`; drop it.
- **SEC-H is now DETERMINISTIC via the Roslyn analyzer (`analyzers/BoxfusionTlc.SecAnalyzers`, DiagnosticAnalyzer `SEC_H`) — quarantine RETIRED.** A text grep could not separate `person.FullName` (PII) from `customType.FullName`/`workflowType.FullName` (reflection): the `\bType\.FullName` exclusion missed the longer camelCase identifiers and the `rg | rg -v` pipe executed inconsistently (operators returned 0, 10, 14 sites for the "same" command). The analyzer resolves it with the semantic model: a `Log*`/`Logger.Info`/`logger.*` call passed an interpolated/concat string containing a frozen POPIA property access (`IdentityNumber|PersalNo|PersalNumber|FullName|DateOfBirth|LeaveReason`, plain `x.P` **or** conditional `x?.P`) raises `SEC-H@<path>#<Type>.<Member>` **iff the property's declaring type is not `System.Type`/`System.Reflection.*`** — so `person.FullName` fires and `customType.FullName` does not. Findings carry `non_deterministic:false` and enter the acceptance diff. `SEC-H@telemetry` stays the fixed `NOT-ASSESSED(no-telemetry)` record; the frozen POPIA token list is unchanged. Proven on pd-Hcm `7fc13b84`: 5 PII-in-log sites, 7 `System.Type.FullName` decoys excluded, byte-identical across two runs. No build ⇒ fixed `SEC-H@analyzer` `NOT-ASSESSED(no-build)` — never a silent pass.
- **All capability-gated NOT-ASSESSED records are MANDATORY fixed anchors — every operator emits every one, always:** `SEC-C@sln:DefaultEndpointAccess`, `SEC-D@probe`, `SEC-E@scanner:gitleaks`, `SEC-H@telemetry`, **`SEC-K@forms`** (one operator omitted it, shifting fix-order). Fix-order (operating-standard §6) ranks only **scored** findings (Critical/High/Medium/Low); Info/NOT-ASSESSED records never enter the fix-order list, so their presence can't change it.

**Useful sources without starting the app:** `Web.Host/obj/<config>/<framework>/ApiEndpoints.json` (routes); `$DLL` decompiled with `ilspycmd` (anonymous attributes, default settings, custom checkers). **Read a validator/checker body before calling it empty** — validating input is not authorising the caller.

**Route-prefix reality (pins every live probe).** Custom-module app-services are **not** under `/api/services/app/` — they are `/api/services/{moduleName}/...`, where `moduleName` is the `CreateControllersForAppServices(..., moduleName:)` argument in the module's `PreInitialize()` (e.g. `SaGovLeave`, `Leave`). Resolve the prefix from the module before probing; a guessed `/app/` path 404s and a careless operator reads "not reachable". Disambiguate with the 405-vs-404 trick (wrong verb → 405 = route exists, 404 = wrong path).

---

## SEC-I: Settings endpoints (run first; urgent stop)
Shesha 0.43.x–0.44.x `Settings/GetValue` can be called anonymously and return secret settings. **impact_class=secret_exposure, data_sensitivity=secret.**
- **INPUT:** (i) `ilspycmd -t Shesha.Settings.SettingsAppService $DLL` → record the attribute on `GetValueAsync`, `GetValuesAsync`, `GetUserValueAsync`, `GetConfigurationsAsync`, `UpdateValueAsync`, `UpdateUserValueAsync`. (ii) Collect setting names matching `/(password|pwd|secret|key|token|clientsecret|connection ?string|apikey|dsn|smtp|credential)/i` from settings classes/config items. (iii) If `backend_running`: for each secret name, `GET $BASE/api/services/app/Settings/GetValue?Module={m}&Name={n}` with **no** Authorization header.
- **PREDICATE:** `GetValueAsync` carries `[AllowAnonymous]` AND (a probe returns HTTP 200 with a non-empty body for a secret name OR `backend_running` absent).
- **VERDICT/ANCHOR:** `SEC-I@pkg:Shesha.Application@$SHA#SettingsAppService.GetValueAsync` + one probe-row anchor per confirmed name `SEC-I@http:GET /api/services/app/Settings/GetValue?Name={n}` (record status + non-empty yes/no + length band; never the value).
- **EVIDENCE:** probe 200 → REPRODUCED; decompile-only (no backend) → VERIFIED-ARTEFACT on the attribute + `NOT-ASSESSED(no-backend)` on the probe dimension.
- **REMEDIATION `PLAN-SEC-I`:** interim case-insensitive gateway/middleware deny-filter on the secret-name regex for the `Settings/GetValue` route (emergency-shortcut register); honour each setting's `ClientAccess`; **rotate every exposed credential this release**; raise the framework defect with the Shesha team (affects all 0.43.x–0.45.1); ask IT whether prod gateway logs show anonymous `Settings/GetValue` hits → precaution vs incident response.
- **REGRESSION TEST:** `Settings_GetValueSecretNamesDenied_Test` — anonymous GetValue for each secret name asserts 403/404; UpdateUserValue as low-priv asserts 403.
- **SEVERITY:** secret_exposure × anonymous, +secret → **Critical**.
- **Version note:** 0.43.34/0.44.2 — `GetValueAsync [AllowAnonymous]`, others gated. 0.45.1 — `GetValueAsync` still anonymous AND `GetConfigurationsAsync` regresses to anonymous; `UpdateValueAsync` loses `[SheshaAuthorize]`. Re-decompile `$DLL`; never assume a later release fixed it.

## SEC-C: Default permissions / "any authenticated". **impact_class=auth_bypass, data_sensitivity per entity.**
- **INPUT:** denominator `N` = concrete classes under `backend/src` whose name ends `AppService` OR deriving from a framework CRUD/workflow base, excluding `obj`/`bin`/test projects (`find backend/src -name '*AppService.cs' -not -path '*/obj/*' -not -path '*/bin/*' | grep -vi '\.tests\?/'`). Numerator `A` = those with `[AbpAuthorize("…")]`/`[SheshaAuthorize(…)]` carrying a **permission name** (`grep -l '\[AbpAuthorize("\|\[SheshaAuthorize("'`). Plain `ControllerBase` count reported separately. `DefaultEndpointAccess`: canonical = `ilspycmd` the SecuritySettings type on `$DLL`; corroborate live with `GET Settings/GetValue?Name=Shesha.Security` if `backend_running`. List dynamic-CRUD-exposed entities carrying status/owner/tenant/PII fields. Also: permissions declared but never seeded (`[AbpAuthorize("X")]` names vs permission-definition/seeder set); `requireAllPermissions:false`; tenant filter disabled.
- **PREDICATE:** `DefaultEndpointAccess ∈ {AnyAuthenticated(3), Disabled}` AND `A/N < 0.10` → root-cause finding. Each sensitive entity whose CRUD `PermissionedObject` is absent (= open-at-default — **absence ≠ locked**) or access ∈ {2,3} → one finding. (If `N < 5`: `NOT-ASSESSED(too-few-services:$N)` or LOW note — a demo/harness, not "the whole system is unauthorised".)
- **VERDICT/ANCHOR:** `SEC-C@<solution>:DefaultEndpointAccess={value}` + `SEC-C@<solution>:authorize-ratio={A}/{N}` + per-entity `SEC-C@http:PUT /api/dynamic/{Module}/{Entity}/Crud/Update`.
- **EVIDENCE:** decompiled DefaultEndpointAccess → VERIFIED-ARTEFACT (needs no backend); +live → REPRODUCED. Authenticated-reachability needs `low_priv_account` → else `NOT-ASSESSED(no-low-priv-user)` (anonymous 401 only proves the authenticated-default exists).
- **REMEDIATION `PLAN-SEC-C`:** set `DefaultEndpointAccess=RequiresPermissions`; named `[AbpAuthorize]` on every write/admin action; ship sensitive-entity CRUD permissions via `api-permissions-manifest` (not SQL); global specifications for row-level scope; defer the implementation to `shesha-access-control`. Note: a `@Get` set to RequiresPermissions with an **empty** permission list rejects everyone incl. admins.
- **REGRESSION TEST:** `AuthorizationInventory_NoInheritedOrAnyAuthenticated_Test` — joins `EntityConfig.GetAll` + `PermissionedObject.GetAll`, drops `notImplemented:true`, fails on any action absent OR access∈{2,3} not on a reviewed allow-list. **Named as the regression test of every SEC-A/B/C/K finding.**
- **SEVERITY:** auth_bypass × any_authenticated, +data_sensitivity of the reachable entities (special-category present → +1) → **Critical**.

## SEC-A: Access decided by what the browser sends (BOLA / param-trust). **impact_class=auth_bypass.** **DETERMINISTIC (Roslyn analyzer).**
- **DETECT (deterministic instrument):** run the analyzer — `dotnet analyzers/.../BoxfusionTlc.SecDriver.dll --solution <sln> --repo-root <repo> --out findings.json --commit <sha>` (DiagnosticAnalyzer `SEC_A`). It enumerates the candidate surface over the semantic model, not a grep; its `findings.json` records are the SEC-A verdict. Two runs on one commit are byte-identical. If no `Compilation` (backend not buildable) → fixed `SEC-A@analyzer` `NOT-ASSESSED(no-build)`.
- **INPUT (what the analyzer reads):** public methods of app-service/controller types (base chain `ApplicationService`/`ControllerBase`/`AbpController`, or name `*AppService`/`*Controller`) taking a `Guid`/`Guid?` actor-id parameter `person|profile|owner|user|employee|appointment|farmer|delegat…Id`; **exclude** `creatorUserId|lastModifierUserId|deleterUserId`. (Also note for manual review, not analyzed here: forgeable JWT claim trust (ties SEC-E); `Abp.TenantId` header spoofing.)
- **PREDICATE:** the action uses the id parameter **as the actor** (it flows into a repository/LINQ read or an `==`/`!=` scope filter against an entity `…Id`, excluding `Guid.Empty`/`null`/`default` guards) AND the body has **no** `AbpSession`/`GetLoggedInPersonAsync`/`GetCurrentPersonAsync`/`CurrentUser` cross-check of that id.
- **VERDICT/ANCHOR:** `SEC-A@<path>#<Service>.<Method>` ("actor from param, no session cross-check"). Keeps its own id even when grouped under a root cause with SEC-K/SEC-B — never "folded away".
- **EVIDENCE:** `VERIFIED-ARTEFACT` (the analyzer is a scan producing an anchored artifact, operating-standard §4); REPRODUCED needs `low_priv_account` → else the reachability dimension `NOT-ASSESSED(no-low-priv-user)`.
- **REMEDIATION `PLAN-SEC-A`:** derive the actor's scope on the server from `AbpSession`/claims in one shared resolver; resolve the person with `GetLoggedInPersonAsync()` (**never `EnterpriseSessionBase.PersonId`** — override-only, null for ordinary requests); treat request parameters as view filters inside that scope; row-level rules via global specifications.
- **REGRESSION TEST:** `AccessControl_ActorFromSessionNotParameter_Test` — low-priv user calls with another user's id → 403/scoped-empty.
- **SEVERITY:** auth_bypass × any_authenticated → **Critical** (−1 band if the action is scoped-read only → High).

## SEC-B: Single-record endpoints without the list's rules (IDOR). **impact_class=data_exposure_pii.**
- **INPUT:** enumerate every endpoint taking an id/natural key — `Get(id)`, PDF/report/download controllers, **`/api/StoredFile/Download?id=` and `DownloadZip`** (the most common Shesha IDOR), `GetByIds`/`GetList?ids=`, GraphQL `node(id:)`, by-phone. For each, resolve the scope symbol it calls.
- **PREDICATE:** the list endpoint for entity `T` applies scope symbol `S`; the by-id endpoint for `T` does **not** call `S` and is not admin-permissioned.
- **VERDICT/ANCHOR:** `SEC-B@<path>#<Controller>.<Method>` ("list uses S, by-id does not"; record id type int vs GUID).
- **EVIDENCE:** CODE-ONLY; REPRODUCED needs `low_priv_account` → else `NOT-ASSESSED(no-low-priv-user)`.
- **REMEDIATION `PLAN-SEC-B`:** apply the shared scope specification `S` on every by-id/by-key endpoint; return **not-found (404)** not forbidden so ids can't be enumerated; for `StoredFile`, authorise the owning entity before streaming.
- **REGRESSION TEST:** `Idor_ByIdEndpointsReturnNotFoundCrossScope_Test` — low-priv requests another scope's synthetic record by id → 404.
- **SEVERITY:** data_exposure_pii × any_authenticated, +popia_special → **Critical** (basic PII → High).

## SEC-K: Business-flow security (cross-area). **Each sub-predicate is its own finding; the Architect groups them at plan time (operating-standard §6), never collapsed at authoring.**
- **INPUT/PREDICATES (one finding per hit):**
  - `SEC-K@form:<module>/<name>` (status-write) — a form script PUTs a generic `.../Crud/Update` whose body includes `requestStatus|status|ownerId|approverId|approveWithoutPay` AND a separate `Process/UserTaskComplete` call. **impact_class=data_integrity.**
  - `SEC-K@form:<module>/<name>#decisionUid` — `completeUserTask(todo, '<literal>')` passes a client-side **literal** or display-name-matched `decisionUid` (route chosen in the browser). **data_integrity.**
  - `SEC-K@<path>#<Type>.<Member>` (literal-guard) — `if (<param> != "<literal>")` guards an integration action (length band only; if repo is public → reachability=anonymous). **auth_bypass.**
  - `SEC-K@<path>#<Type>.<Member>` (http-get-mutation) — `[HttpGet]` action whose body mutates/sends/completes a step. **data_integrity.**
  - `SEC-K@<path>#<Controller>.<action>` (test-endpoint) — `ControllerBase` + `[Http*]` + no `[Authorize]` + (`"testing"`/`#region Debug`/`simulate`/`generate-test`) touching an integration (FTP/PERSAL/payroll). **auth_bypass.**
  Also: TOCTOU/replay (two-call pattern not idempotent/single-UoW); completing a task on a retired workflow version; generated-PDF actor/role not verified.
- **EVIDENCE:** generic-CRUD reachability REPRODUCED-via-anon-401 (auth-only gate) on its own anchor; form-script/code facts VERIFIED-ARTEFACT; authenticated reachability needs `low_priv_account`.
- **REMEDIATION `PLAN-SEC-K`:** one app-service command per business action (save + status + task-complete in **one unit of work**, actor from session via `GetLoggedInPersonAsync()`, route by a stable decision key, caller==assignee + applicant scope verified); generic CRUD rejects status/owner/approver fields (SEC-L); replace literal guards with `[AbpAuthorize("…")]`; environment-gate + permission or delete every test/debug/simulate endpoint; row scope via global specification.
- **REGRESSION TEST:** `BusinessFlow_StatusAndRouteServerEnforced_Test` — low-priv (a) sets status via generic CRUD → rejected; (b) completes a task not assigned → 403; (c) calls a former literal-guard endpoint without permission → 403.
- **SEVERITY (per anchor):** status-write/http-get-mutation data_integrity × any_authenticated → High; public-repo literal-guard auth_bypass × anonymous → Critical.

## SEC-D: Anonymous endpoints. **impact_class=info_leak (or the stronger class of what the endpoint returns/does).**
- **INPUT:** grep `[AbpAllowAnonymous]`/`[AllowAnonymous]` (class AND method); permissioned-objects set to anonymous; plain `ControllerBase` with no `[Authorize]`; if `backend_running`, `curl` no-token `{/elmah, /elmah/api/errors, /ui/playground, /graphql, /swagger, /hangfire, /signalr-appender}`. **Opening-move cross (required):** anonymous × (returns secret/OTP OR mutates).
- **PREDICATE:** endpoint is anonymous AND not on the legitimate-anon allow-list {login, OTP send/verify, token-handshake, health}. Cross-hit (returns secret/OTP/mutates) escalates the impact_class.
- **VERDICT/ANCHOR:** `SEC-D@http:GET /elmah`, `SEC-D@http:GET /ui/playground`, etc. (+ HTTP status). Distinguish class-level vs method-level anon.
- **EVIDENCE:** probe 200 → REPRODUCED; no backend → `NOT-ASSESSED(no-backend)` on the probe + static CODE-ONLY.
- **REMEDIATION `PLAN-SEC-D`:** require auth, or for genuine public endpoints signed requests/API keys + rate limits; webhooks verify source signature, never act on empty/unverified token; proxy-gate or strip `/elmah`, Swagger, GraphQL Playground, Hangfire in non-dev; confirm the reverse proxy does not expose them in prod. Un-rate-limited anonymous OTP = SMS-bomb/enumeration → add rate limiting.
- **REGRESSION TEST:** `AnonymousSurface_OnlyAllowlistedEndpointsReturn200Anon_Test`.
- **SEVERITY:** `/elmah` info_leak × anonymous → High; Playground info_leak × anonymous → High; health (allow-listed) → no finding.

## SEC-E: Secrets. **impact_class=secret_exposure (JWT key = auth_bypass), data_sensitivity=secret.**
- **INPUT:** (i) `gitleaks detect --source . --no-git` (working tree) AND `gitleaks detect --source .` (history). (ii) Seam grep over config + code: `Password=|SecurityKey|ClientSecret|ApiKey|ConnectionString|BearerToken` in **all** `appsettings*.json` (incl. commented lines; working-tree on zero-commit repos), the `Integrations`/per-partner block (flag `EnvironmentType:"LIVE"` beside a credential), module `.WithDefaultValue(`/`RegisterSettingAccessor` literals, `DangerousAcceptAnyServerCertificateValidator`/`ServerCertificateCustomValidationCallback=>true`, CI/pipeline/`docker-compose*`/helm `values*`/`launchSettings.json`, `*.bacpac`/`*.backup` (SEC-E owns committed dumps), `NEXT_PUBLIC_*`. (iii) Count per-developer `appsettings.{Name}.json` sharing one secret (report the count, never the developer names). Entropy threshold for "long random string": Shannon ≥4.0 bits/char over ≥20 chars, else defer to gitleaks. Known-empty-default allow-list: `string.Empty`, `""`, `changeme`, `<...>`.
- **PREDICATE:** gitleaks reports a finding (minus triaged FPs) OR a seam grep hits a literal not on the allow-list. **If gitleaks absent → `SEC-E@scanner:NOT-ASSESSED(no-secret-scanner)` as a first-class line**, grep runs as a stated spot-check (never "clean").
- **VERDICT/ANCHOR:** `SEC-E@<path>#key:<json.path>` (+ presence + length band; proof = SHA-256 hash compare to deployed config, match/no-match only). The committed-key fact is VERIFIED-ARTEFACT; forge-ability is a CODE-ONLY inference.
- **REMEDIATION `PLAN-SEC-E`:** move to pipeline/key-vault; **rotate** (committed = compromised, incl. history); fail-fast if unset outside Development; gitignore the per-dev `appsettings.{Name}.json` pattern; remove committed dumps from repo **and history**; enable GitHub push-protection + a gitleaks CI step.
- **REGRESSION TEST:** `SecretScan_GitleaksCleanTreeAndHistory_CI`.
- **SEVERITY:** JWT key auth_bypass × anonymous(public repo)/any_authenticated(private), +secret → **Critical**; committed QA test creds → High, drop to Low if confirmed not reused in prod (reachability local_only).

## SEC-O: Security headers, CSP, HSTS, CORS, clickjacking. **(sub-checks, each own id).**
- **INPUT:** back end — grep `Startup`/pipeline for `UseHsts`, a security-headers middleware, `Headers.Add`, and the CORS policy builder; if `backend_running`, `curl -I` a **route set** `{/, an API route, /elmah, /swagger}`. Front end — `next.config.js` `headers()`; `productionBrowserSourceMaps`.
- **PREDICATES (each its own anchor+severity):**
  - O1 `SEC-O@<path>#Startup.Configure` — no `UseHsts` AND no security-headers middleware. **impact_class=info_leak** → Low.
  - O2 `SEC-O@<path>#Startup.Cors` — CORS builder has `SetIsOriginAllowed(*=>true)` AND `AllowCredentials()`. **impact_class=auth_bypass** × anonymous → **Critical**.
  - O3 `SEC-O@<path>#csp` — a CSP exists containing `unsafe-inline`/`unsafe-eval`. info_leak → Low.
  - O4 `SEC-O@next.config.js#headers` — no `headers()` block (and/or `productionBrowserSourceMaps:true`). info_leak → Low.
  - O5 `SEC-O@http:<route>` — a probed route returns 200 with **none** of {X-Content-Type-Options, X-Frame-Options/frame-ancestors, Strict-Transport-Security}. info_leak → Low.
  Also: auth-cookie flags (Secure/HttpOnly/SameSite), `Cache-Control: no-store` on authenticated responses.
- **EVIDENCE:** CORS proof `Origin: https://evil.example.com` → reflected `Access-Control-Allow-Origin` + `Allow-Credentials:true` = REPRODUCED; header presence needs backend → else `NOT-ASSESSED(no-backend)` + static middleware read CODE-ONLY.
- **REMEDIATION `PLAN-SEC-O`:** security-headers middleware on the API + `headers()` in `next.config.js` (HSTS incl. subdomains, nosniff, Referrer-Policy, frame-ancestors/X-Frame-Options, Permissions-Policy; CSP report-only → enforce); replace `SetIsOriginAllowed(_=>true)` with the configured `App:CorsOrigins` allow-list; disable prod source maps; set Secure/HttpOnly/SameSite on auth cookies.
- **REGRESSION TEST:** `SecurityHeaders_PresentAndCorsAllowlisted_Test` — required headers per route; untrusted Origin not reflected.

## SEC-L: Mass assignment / over-posting. **impact_class=data_integrity (or privilege_escalation when role/clearance).**
- **INPUT:** grep `CreateMap<{Dto},{Entity}>()`, `.ReverseMap()`, `[AutoMap(typeof({Entity}))]`, DTOs inheriting the entity/`FullAuditedEntityDto`+nothing, app-service params typed as the entity; decompile the CRUD base to see which properties `Update` writes. Protected-field set: `IsApproved|Status|requestStatus|TenantId|OwnerId|PersonId|RoleNames|<audit>|Price|SecurityClearance|IdentityNumber|settable Id` (+ collections/nav).
- **PREDICATE:** a bindable path (DTO→entity map or entity-typed param) exposes ≥1 protected field, with no `ForMember(Ignore)`/validator excluding it. If no app-service consumes the DTO → `latent` (reachability=local_only/0).
- **VERDICT/ANCHOR:** `SEC-L@<path>#<MappingProfile>` or `SEC-L@http:PUT /api/dynamic/.../Crud/Update` (+ the protected field(s) + wired|latent).
- **EVIDENCE:** CODE-ONLY; REPRODUCED needs `low_priv_account`.
- **REMEDIATION `PLAN-SEC-L`:** narrow input DTO of only caller-settable fields; server sets status/owner/tenant/approver/role from session or workflow; `[DisableAuditing]`/ignore rules on protected members; for sensitive dynamic CRUD restrict it (SEC-C) + validate the mutable set in a Fluent validator.
- **REGRESSION TEST:** `MassAssignment_ProtectedFieldsIgnoredOnBind_Test` — low-priv create/update with `{"isApproved":true,"ownerId":<other>,"requestStatus":<x>}` → ignored/400/403.
- **SEVERITY:** wired data_integrity × any_authenticated → High; latent → Medium (reachability 0).

## SEC-M: Unrestricted file upload (four sub-predicates, each own anchor). **impact_class=info_leak→data_integrity by web-root.**
- **INPUT:** grep `IFormFile`, `IStoredFileService`, `SaveFile|UploadFile`, `Request.Form.Files`, `[DisableRequestSizeLimit]`, `Path.Combine(` with a user filename; read the four controls per upload action.
- **PREDICATES:** M1 no extension/content-type **allow-list** (block-list ≠ allow-list); M2 no size cap; M3 filename not sanitised for `..`/absolute/ADS; M4 store inside web root. Each absent control = one `SEC-M@<path>#<Type>.<Member>` (+ which control). Also: zip-slip/decompression-bomb/XXE on xlsx (ties SEC-G); double-extension; SVG/HTML stored-XSS on serve-back.
- **EVIDENCE:** CODE-ONLY; REPRODUCED needs backend+upload.
- **REMEDIATION `PLAN-SEC-M`:** allow-list extensions AND sniff content type; cap size; server-side storage name (ignore client filename for the path); store outside the web root, serve via an authorised endpoint; parse office formats with XXE disabled + decompression limits; malware-scan where available.
- **REGRESSION TEST:** `FileUpload_RejectsDisallowedTypeOversizeTraversal_Test`.
- **SEVERITY:** size-cap-only, stored outside web root → Low; content-type unchecked + served from web root → Medium.

## SEC-N: SSRF. **impact_class=info_leak (SSRF-to-internal).**
- **INPUT:** grep `new HttpClient`, `GetAsync|PostAsync`, `WebRequest`, `RestClient`, `FtpWebRequest` where base-address/URL is a variable; webhook/callback registration endpoints; settings-driven base URLs. Define "locked" config = NOT writable via `UpdateUserValue`/dynamic CRUD by a non-admin (test it).
- **PREDICATE:** the outbound target is sourced from (request body/param) OR (an entity field) OR (a non-admin-writable setting) AND there is no host/scheme allow-list + private-range block.
- **VERDICT/ANCHOR:** `SEC-N@<path>#<Type>.<Member>` (+ source: request|entity|user-editable-setting).
- **EVIDENCE:** CODE-ONLY; REPRODUCED needs a local listener + backend.
- **REMEDIATION `PLAN-SEC-N`:** allow-list hosts + schemes; resolve-and-validate the destination (block loopback/link-local/private; re-validate after redirects or disable them); never let a user-editable setting supply an outbound base URL without the allow-list; timeouts + response size caps. Covers non-HTTP schemes (PERSAL FTP), DNS-rebind/TOCTOU, headless-renderer SSRF.
- **REGRESSION TEST:** `Ssrf_OutboundUrlAllowlistBlocksInternal_Test`.
- **SEVERITY:** settings two-step info_leak × low_priv → Low; request-driven internal fetch × any_authenticated → Medium.

## SEC-G: Injection & unsafe input (per-vector predicate; emit a verdict line for each vector even when empty, e.g. `SEC-G@xss=none`).
- **INPUT/PREDICATES:** XSS → `dangerouslySetInnerHTML`/Razor string-concat; XXE → `XmlReader|XmlDocument|LoadXml` without `DtdProcessing.Prohibit`+null `XmlResolver`; deserialization → `TypeNameHandling!=None|BinaryFormatter|LosFormatter`; open-redirect → `Redirect(var)`/`returnUrl` without `IsLocalUrl`; **HQL injection** → `CreateQuery(`/`session.CreateQuery` with `+`/interpolation (Shesha-native SQLi analogue); CSV/formula injection → export writing cell values without `'`-prefix/escaping; LDAP/OS-command; ReDoS; SSTI. Finding per hit at `SEC-G@<vector>@<path>#<symbol>`; else `SEC-G@<vector>=none`.
- **EVIDENCE:** CODE-ONLY static; REPRODUCED where probed.
- **REMEDIATION `PLAN-SEC-G`:** per vector — encode on render / parameterised HQL `SetParameter` / `TypeNameHandling.None` / `IsLocalUrl` allow-list / prefix-escape CSV cells / `DtdProcessing.Prohibit`+null resolver.
- **REGRESSION TEST:** `Injection_ParameterisedQueriesAndSafeRender_Test`.
- **SEVERITY:** stored XSS data_exposure × any_authenticated → High; reachable deserialization auth_bypass/RCE → Critical/High.

## SEC-H: Personal data / POPIA. **impact_class=data_exposure_pii, data_sensitivity per field.** **H1 PII-in-logs is DETERMINISTIC (Roslyn analyzer).** Partly a BA-question area; the detectable parts are booleans.
- **DETECT (H1, deterministic instrument):** the same driver runs DiagnosticAnalyzer `SEC_H` — a `Log*`/`Logger.*` call passed an interpolated/concat string with a frozen POPIA property access whose **declaring type is not `System.Type`/`System.Reflection.*`** (resolves `person.FullName` PII vs `customType.FullName` reflection). Its `findings.json` records are the SEC-H H1 verdict; two runs are byte-identical; no build → fixed `SEC-H@analyzer` `NOT-ASSESSED(no-build)`.
- **INPUT/PREDICATES:** H1 (analyzer) `Log*`/`Logger.*` with a PII property **value** interpolated (plain `x.P` or conditional `x?.P`, not a bare mention), declaring type non-reflection → `SEC-H@<path>#<symbol>`; H2 PII property in a route/query-string → finding; H3 a DTO serialises a classed-PII field (ID no./DOB/health/clearance) that **no** consuming form binds → over-exposure finding. Frozen H1 POPIA tokens: `IdentityNumber|PersalNo|PersalNumber|FullName|DateOfBirth|LeaveReason`. POPIA special list: `IdentityNumber, DateOfBirth, health/medical, biometric, religion, race, trade-union, leave-reason, family-relationship`.
- **EVIDENCE:** H1 `VERIFIED-ARTEFACT` (analyzer scan); H2/H3 CODE-ONLY static; telemetry dimension → fixed `SEC-H@telemetry` `NOT-ASSESSED(no-telemetry)` when no App Insights.
- **REMEDIATION `PLAN-SEC-H`:** remove PII values from logs/telemetry (ids/counts only); never put PII in URLs (POST/body); trim DTOs to screen fields; audit special-category reads; confirm scope with the BA.
- **REGRESSION TEST:** `PersonalData_ResponseShapeMatchesAllowlist_Test`.
- **SEVERITY:** PII value in logs data_exposure × low_priv/any_authenticated +popia_special → High.
- **Ask the BA:** which fields are personal/health, who may see them, whether access must be audited.

## SEC-F: SignalR / real-time. **impact_class=data_exposure_pii/info_leak.**
- **INPUT/PREDICATES:** F1 a `Hub`/`AbpHubBase` subclass without `[Authorize]` → `SEC-F@<path>#<Hub>`; F2 a hub method reads a client value to `Groups.AddToGroupAsync` → finding; F3 decompile confirms the framework SignalRProvider builds `HubConnection` without `accessTokenFactory` AND targeted notifications are configured (grep notification-channel config) → framework finding `SEC-F@pkg:...#SignalRProvider`.
- **EVIDENCE:** connect-anonymously REPRODUCED needs backend → else `NOT-ASSESSED(no-backend)`; static no-`[Authorize]` CODE-ONLY.
- **REMEDIATION `PLAN-SEC-F`:** authenticated hubs; server-computed groups from the user's scope; events after commit; tokens scrubbed from logs; route the framework caveat to the Shesha team report.
- **REGRESSION TEST:** `SignalR_HubRequiresAuthAndServerSideGroups_Test`.
- **SEVERITY:** custom anon hub leaking scoped events data_exposure × anonymous → Critical; framework-caveat-only → Low.

## SEC-J: Message consumers as input surface. **impact_class=data_integrity.**
- **INPUT/PREDICATE:** grep `IConsumer<`, `AddMassTransit`, `AddConsumer`. None → `SEC-J@none` (deterministic empty verdict). Else per consumer: mutates state/fetches a URL/forwards a credential AND no source-signature/verification → `SEC-J@<path>#<Consumer>`. Also check broker default-host exposure (OPS-H), outbox/webhook receivers, idempotency/replay.
- **EVIDENCE:** CODE-ONLY static.
- **REMEDIATION `PLAN-SEC-J`:** verify message source/signature; validate content like any request; never take URLs/credentials from messages without an allow-list; idempotency keys; guard broker defaults.
- **REGRESSION TEST:** `MessageConsumer_SourceVerifiedAndValidated_Test`.
- **SEVERITY:** consumer creating users from unsigned messages on a shared broker data_integrity × any_authenticated → High; no consumers → no finding.

---
## Coverage additions — SEC-P..SEC-S + extensions (from the R4 coverage judge)
New checks, written to the same determinism discipline (INPUT→PREDICATE→VERDICT→ANCHOR, fixed severity-inputs, plan_id, named regression test, enumerated root_cause). All part of the `--security-only` closed set; capability-gated dimensions emit the fixed `NOT-ASSESSED` anchor.

### SEC-P: JWT trust configuration. impact_class=auth_bypass, data_sensitivity=secret, RC-no-authz-model.
SEC-E treats the key as a committed secret; nothing checks how tokens are *validated*. Rotating the key does not fix `ValidateAudience=false`.
- **INPUT:** `rg -n "TokenValidationParameters|ValidateIssuer|ValidateAudience|ValidateLifetime|ValidAlgorithms|RequireSignedTokens|RequireExpirationTime" backend/src --type cs`; `Authentication:JwtBearer` block in appsettings.
- **PREDICATE:** any of {`ValidateAudience=false`, `ValidateIssuer=false`, `ValidateLifetime=false`, no `ValidAlgorithms` allow-list, token lifetime > 24h, refresh tokens not rotated, SignOff doesn't revoke}. One finding per failing parameter.
- **ANCHOR:** `SEC-P@<path>#<Type>.<Member>` (e.g. `#Startup.ConfigureTokenAuth`). **EVIDENCE:** CODE-ONLY static (VERIFIED-ARTEFACT if decompiled); `alg:none`/foreign-audience forge is `--deep` REPRODUCED.
- **SEVERITY:** auth_bypass × anonymous (unvalidated audience/issuer) → Critical; lifetime>24h → Medium.
- **PLAN-SEC-P:** set ValidateIssuer/Audience/Lifetime=true, pin `ValidAlgorithms`, short lifetime + rotation + revocation. **TEST:** `Jwt_RejectsForeignAudienceAndNoneAlg_Test`.

### SEC-Q: GraphQL data-plane authorization. impact_class=auth_bypass, data_sensitivity=none, RC-no-authz-model.
The `/graphql` data endpoint is a second read path that may bypass `SheshaAuthorizationFilter` — reopening everything SEC-C closes. (SEC-D's Playground finding is info-leak only; this is the data-plane.)
- **INPUT:** `rg -n "AddGraphQL|UseGraphQL|MapGraphQL|AddGraphQLPlayground|DocumentExecuter|ISchema" backend/src --type cs`; look for depth/complexity validation + introspection gate + per-field authorization.
- **PREDICATE:** GraphQL endpoint present AND (no depth/complexity limit OR introspection enabled non-dev OR no per-field authorization rule). **ANCHOR:** `SEC-Q@http:POST /graphql`.
- **EVIDENCE:** CODE-ONLY static; `--deep`: anon/low-priv query of a PII entity returns rows → Critical REPRODUCED. **SEVERITY:** auth_bypass × anonymous → Critical (static: High pending live).
- **PLAN-SEC-Q:** enforce the permission model in resolvers; disable introspection in prod; add depth/complexity limits. **TEST:** `GraphQL_RequiresPermissionAndLimitsDepth_Test`.

### SEC-R: background-job trust. impact_class=data_integrity, data_sensitivity=business, RC-realtime-messaging.
Who may enqueue/trigger a `[ScheduledJob]` (PERSAL/payroll jobs), and Hangfire-arg deserialization.
- **INPUT:** `rg -n "\[ScheduledJob|IBackgroundJobManager|\.Enqueue\(|RunTrigger|StartJob|EnqueueAll|RecurringJob" backend/src --type cs`; Hangfire serializer settings (`TypeNameHandling`).
- **PREDICATE:** a job-trigger endpoint lacks a named `[AbpAuthorize]` OR job args deserialize with `TypeNameHandling != None`. **ANCHOR:** `SEC-R@<path>#<Type>.<Member>` and `SEC-R@http:POST /api/services/app/ScheduledJob/RunTrigger`.
- **EVIDENCE:** CODE-ONLY; `--deep` enqueue probe REPRODUCED. **SEVERITY:** data_integrity × any_authenticated → High; deserialization-reachable → Critical.
- **PLAN-SEC-R:** `[AbpAuthorize]` on trigger endpoints; `TypeNameHandling.None`; run jobs under an explicit identity. **TEST:** `BackgroundJob_TriggerRequiresPermission_Test`.

### SEC-S: tenant isolation. impact_class=data_exposure_pii, data_sensitivity=popia_special, RC-no-authz-model.
Cross-tenant read via `Abp.TenantId` spoof or a disabled `MayHaveTenant` filter. (SEC-A/C only *mention* it — make it a first-class anchored check.)
- **INPUT:** `rg -n "Abp\.TenantId|SetTenantId|DisableFilter\(.*MayHaveTenant|IMustHaveTenant|CurrentTenant" backend/src --type cs`; whether multi-tenancy is wired (`AbpMultiTenancy`/`MultiTenancyConfig`).
- **PREDICATE:** an app-service/consumer reads `Abp.TenantId` from the request OR calls `DisableFilter(AbpDataFilters.MayHaveTenant)` outside a host/admin path. **ANCHOR:** `SEC-S@<path>#<Type>.<Member>`. If no multi-tenancy wired → `SEC-S@tenancy` `NOT-ASSESSED(single-tenant)` (fixed anchor).
- **EVIDENCE:** CODE-ONLY; `--deep` cross-tenant read REPRODUCED. **SEVERITY:** data_exposure_pii × any_authenticated + popia_special → Critical.
- **PLAN-SEC-S:** derive tenant from the authenticated context only; never honour a request-supplied tenant; keep `MayHaveTenant` enabled. **TEST:** `Tenancy_NoCrossTenantRead_Test`.

### Extensions to existing checks (fixed predicates; fold into the named check)
- **SEC-G +SSTI (fix the false-clean):** `SEC-G@ssti` raise IFF `rg -n "\.Render\(|RazorEngine|Scriban|Handlebars|Liquid|ITemplateRenderer|Process/ExecuteExpression" backend/src --type cs` matches a template/expression arg sourced from request/entity (the ~12 `*PdfController.GenerateAndDownload*` + notification templates). impact_class=auth_bypass (RCE-class) → Critical/High. **SEC-M +M5 zip-slip/XXE/bomb:** on each import, raise IFF the OOXML/zip parser (EPPlus/ClosedXML/NPOI/OpenXml) validates no entry path / disables no DTD / caps no decompression → `SEC-M@<Type>.StartImportAsync` control=zip-slip|xxe|bomb, impact_class=data_integrity → Medium/High. **SEC-O +O6 CSRF:** cookie-auth endpoint without `[ValidateAntiForgeryToken]`/`AutoValidateAntiforgeryToken` → `SEC-O@antiforgery` Low (JWT-bearer paths exempt). **SEC-K +TOCTOU:** a state-changing action done as two HTTP calls (not one UoW) with no idempotency key → `SEC-K@<Type>.<Member>#toctou`. **SEC-B +global-spec:** a PII entity with a live CRUD `GetAll` and no registered `[GlobalSpecification]`/`ShaSpecification<T>` → `SEC-B@http:GET /api/dynamic/{Module}/{Entity}/Crud/GetAll`, +popia_special → Critical (`--deep` two-principal totalCount proof). **SEC-C +config-tamper endpoints:** enumerate the fixed set `FormConfiguration/UpdateMarkup`, `PermissionedObject/Update`, `Permission/Create`, `ModelConfigurations`, `ReferenceList/*` — each `NOT-ASSESSED(no-backend)` static, REPRODUCED `--deep`.

### `--deep` closers for the false-convergence spots (coverage judge)
When a backend + low-priv user + restored DB are in the manifest, the `--deep` path MUST run these (both static operators are otherwise blind): DefaultEndpointAccess live read + anon PII-entity `GetAll` probe (SEC-C); PermissionedObject collection per entity (SEC-C); two-principal object-level `GetAll`/by-id test (SEC-B); `/elmah/api/errors` token-capture → escalate SEC-D to Critical if a live Bearer token is stored; GraphQL sensitive-entity query (SEC-Q); anonymous probe of the PERSAL test endpoints (SEC-K). Each upgrades its finding from CODE-ONLY to REPRODUCED.

## Framework-defect candidates (→ `templates/shesha-team-report.md`, only after reproduced)
SEC-I anonymous `Settings/GetValue`; DefaultEndpointAccess=AnyAuthenticated insecure default; SignalR anonymous-handshake caveat. A hit on a framework table/behaviour is never a finding against the system's own developers.
