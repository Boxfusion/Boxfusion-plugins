# Check registry

**Instantiates `determinism-standard.md` §2–§6 for every check.** One row per CHECK-ID: the three scored-severity inputs (so severity is *derived*, not asserted), the anchor form, the capability it needs, its sub-area (team-split), its `root_cause`, and whether it is **DET** (a text scan decides it reproducibly → enters the acceptance diff) or **ND** (needs a live probe or semantic analysis → `non_deterministic:true`, dropped from the diff until its instrument lands). This is the single source of truth the code (`catalog_schema.py`, `findings.py`, `verify_run.py`) and the other two skills key off.

## Severity scoring key (determinism-standard §4)

`severity = base(impact_class, reachability)`, then shift one band per `data_sensitivity`:

| impact_class \ reachability | anonymous | any_authenticated | low_priv | admin_only | local_only |
|---|---|---|---|---|---|
| auth_bypass | Critical | High | High | Medium | Low |
| data_exposure_pii | Critical | High | High | Medium | Low |
| data_integrity | High | High | Medium | Medium | Low |
| dos | High | Medium | Medium | Low | Low |
| info_leak | High | Medium | Low | Low | Low |
| maintainability | Low | Low | Low | Low | Low |

`data_sensitivity`: `popia_special` +1 band, `pii_basic` +0/+1 (per check), `business` +0, `none` −0. Capped at Critical. **Evidence level is not an input** (§3).

---

## A — Web host config (Startup.cs). Capability: static. Sub-area: SC (A9/A10/A11 → AC).

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| A1 | CORS origin allowlist absent | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-cors |
| A2 | CORS wildcard origin | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-cors |
| A3 | CORS wildcard **+ credentials** | auth_bypass | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-cors |
| A4 | GraphQL Playground exposed | info_leak | anonymous | none | `startup#UseGraphQLPlayground` | DET presence / **ND** guard | RC-sec-starter-surface |
| A5 | Swagger UI / JSON exposed | info_leak | anonymous | none | `startup#UseSwaggerUI` | DET presence / **ND** guard | RC-sec-starter-surface |
| A6 | Security-headers middleware absent | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-headers |
| A7 | CSP header absent | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-headers |
| A8 | HSTS absent | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-headers |
| A9 | **SheshaAuthorizationFilter not registered** (master switch) | auth_bypass | anonymous | none | `startup#Startup.ConfigureServices` | DET | RC-sec-authz-filter |
| A10 | Hangfire dashboard unguarded | auth_bypass | anonymous | none | `startup#UseHangfireDashboard` | DET presence / **ND** guard | RC-sec-starter-surface |
| A11 | Elmah error log exposed | info_leak | anonymous | pii_basic | `startup#UseElmah` | DET presence / **ND** probe | RC-sec-starter-surface |
| A12 | No environment guard in Configure | info_leak | anonymous | none | `startup#Startup.Configure` | DET | RC-sec-starter-surface |

*Guard detection (A4/A5/A10/A11 — "is it inside an `if(env)`/auth block?") is **ND** until a Roslyn/middleware-order check exists; presence is DET.*

---

## B — appsettings*.json committed secrets & config. Capability: static + git. Sub-area: SC.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| B1 | JWT `SecurityKey` literal committed | auth_bypass | anonymous | none | `<path>#key:Authentication:JwtBearer:SecurityKey` | DET | RC-sec-committed-secret |
| B2 | `EncryptionPassPhrase` not set | data_integrity | any_authenticated | none | `<path>#key:EncryptionPassPhrase` | DET | RC-sec-config |
| B3 | `CorsOrigins` populated (wildcard/stale) | info_leak | anonymous | none | `<path>#key:App:CorsOrigins` | DET capture / **ND** stale | RC-sec-cors |
| B4 | Connection-string password literal | data_exposure_pii | admin_only | none | `<path>#key:ConnectionStrings:Default` | DET (literal-vs-reference) | RC-sec-committed-secret |
| B5 | Committed SMTP/SMS/API credential | data_exposure_pii | admin_only | none | `<path>#key:<Section>:<Key>` | DET | RC-sec-committed-secret |
| B6 | Azure-env override consistency | maintainability | local_only | none | `<path>#key:IsAzureEnvironment` | **ND** (deployment context) | RC-sec-config |
| **B7** *(was `G1`)* | Secrets in tracked config / git history | data_exposure_pii | anonymous | none | `<path>#key:<key>` + `git:<sha>` | DET (sha256+length only) | RC-sec-committed-secret |

*`G1-secrets-in-tracked-config` is **renamed B7** to end the `G`-prefix collision (baseline `G` is the anonymous allowlist policy, not a check).*

---

## C — App services / controllers. Capability: static (+ live PermissionedObject for effective access). Sub-area: AC.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| C1 | Service with no class-level auth attribute | auth_bypass | any_authenticated | pii_basic | `<path>#<Type>` | DET (attribute absence) / **ND** "sensitive" | RC-sec-no-authz |
| C2 | `AllowAnonymous` on a non-public endpoint | auth_bypass | anonymous | business | `<path>#<Type>.<Member>` | DET attribute / **ND** "genuinely public" | RC-sec-no-authz |
| C3 | Write method less protected than reads | auth_bypass | any_authenticated | business | `<path>#<Type>.<Member>` | **ND** (per-method binding) | RC-sec-no-authz |
| C4 | Custom method on a DynamicCrud subclass | auth_bypass | any_authenticated | business | `<path>#<Type>.<Member>` | **ND** (semantic) | RC-sec-no-authz |
| C5 | Entity read/write with no permission check | data_exposure_pii | any_authenticated | pii_basic | `<path>#<Type>.<Member>` | **ND** (dataflow → Roslyn SEC_A) | RC-sec-no-authz |
| C6 | Workflow task / scheduled job as endpoint | auth_bypass | any_authenticated | business | `<path>#<Type>` | **ND** (+ live probe) | RC-sec-rt-trust |

---

## D — Entities & CRUD exposure. Capability: static decl; live admin for effective access. Sub-area: AC/ID.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| D1 | Entity with CRUD and no Entity.Action permission | auth_bypass | any_authenticated | pii_basic | `db:<Entity>` | **ND** (live effective access) | RC-sec-no-authz |
| D2 | Personal-data entity any-authenticated-readable | data_exposure_pii | any_authenticated | popia_special | `db:<Entity>` | **ND** (name heuristic + live) | RC-sec-no-authz |
| D3 | `DisableGenerateApplicationService` inert (still answers) | auth_bypass | any_authenticated | pii_basic | `<path>#<Type>` + `http:GET /api/dynamic/…/Crud/GetAll` | DET decl / **ND** probe | RC-sec-no-authz |
| D4 | Join/audit/internal entity exposed for write | data_integrity | any_authenticated | business | `db:<Entity>` | **ND** | RC-sec-no-authz |
| D5 | No global specification anywhere (row-level) | data_exposure_pii | any_authenticated | pii_basic | `sln:global-specifications=0` | DET absence / **ND** "required" | RC-sec-no-rowfilter |

*D5 **derives High** (data_exposure_pii × any_authenticated): a solution with **no** global specification anywhere has no row-level security at all — any authenticated user can read any row. The per-entity "this PII entity lacks a spec" is the same defect at entity granularity (H5, also High). The scoring table governs; an earlier draft said Medium and is superseded (resolves the baseline-vs-code severity flag from the harness worker).*

**root_cause registrations** (determinism-standard §6): `RC-sec-bola` (SEC-A, H1–H4), `RC-sec-pii-logging` (SEC-H), `RC-sec-cors`, `RC-sec-headers`, `RC-sec-committed-secret`, `RC-sec-no-authz`, `RC-sec-no-rowfilter`, `RC-sec-token`, `RC-sec-weak-auth`, `RC-sec-dos`, `RC-sec-starter-surface`, `RC-sec-rt-trust`, `RC-sec-config`, `RC-sec-deps`, `RC-sec-authz-filter`, `RC-sec-orphaned-permission` (SEC-U), `RC-sec-upgrade-drift` (SEC-DRIFT, SEC-RESET, SEC-GONE), `RC-sec-anon-settings` (SEC-I), `RC-sec-input-integrity` (SEC-L, SEC-M, SEC-V, SEC-G, SEC-N) — the closed `RC-sec-*` set.

---

## E — Live configuration. Capability: live backend + admin (+ PermissionedObject export). Sub-area: AC/SC.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| E1 | `defaultEndpointAccess == 5` (AnyAnonymous) | auth_bypass | anonymous | business | `dmv:setting:Shesha.Security.defaultEndpointAccess` | **ND** (live; DET once value captured) | RC-sec-no-authz |
| E2 | `swaggerUiEnabled` in prod | info_leak | anonymous | none | `dmv:setting:…swaggerUiEnabled` | **ND** (live) | RC-sec-starter-surface |
| E3 | Password `RequiredLength` < 8 | auth_bypass | anonymous | none | `dmv:setting:PasswordComplexity.RequiredLength` | **ND** (live) | RC-sec-weak-auth |
| E4 | Default admin credentials accepted | auth_bypass | anonymous | none | `http:POST /api/TokenAuth/Authenticate` | **ND** (probe) | RC-sec-weak-auth |
| E5 | High Inherited-access rate | info_leak | any_authenticated | none | `dmv:permissionedobject-coverage` | **ND** (no threshold → define) | RC-sec-no-authz |
| E6 | `RequiresPermissions` empty (deny-all) | dos | admin_only | none | `dmv:permissionedobject:<record>` | **ND** (live; DET once captured) | RC-sec-config |
| E7 | Low entity-permission coverage | auth_bypass | any_authenticated | pii_basic | `dmv:entity-permission-coverage` | **ND** (no threshold → define) | RC-sec-no-authz |
| E8 | Security headers absent on a live response | info_leak | anonymous | none | `http:response-headers` | **ND** (capture not implemented) | RC-sec-headers |

---

## F — Probe set (anonymous / low-priv). Capability: live backend (+ low_priv for lowpriv probes). Sub-area: AC (Otp/workflow → RT). All **ND** (live state); an OPEN verdict is **REPRODUCED** evidence. Anchor: `http:<VERB> <route>`. Each probe's `severityIfOpen` maps to `{impact_class=auth_bypass, reachability=anonymous|low_priv}`.

## H — Object-level authorization (BOLA). Capability: live + admin + **low_priv**. Sub-area: AC (H4→RT). All **ND** (probe) — the static half is the Roslyn **SEC_A** analyzer.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | root_cause |
|---|---|---|---|---|---|---|
| H1 | IDOR — read another's record by id | data_exposure_pii | low_priv | popia_special | `http:GET /api/services/app/Entities/Get` + `db:<Entity>` | RC-sec-bola |
| H2 | List-scope — unscoped GetAll | data_exposure_pii | low_priv | popia_special | `http:GET /api/services/app/Entities/GetAll` + `db:<Entity>` | RC-sec-bola |
| H3 | File-ownership bypass | data_exposure_pii | low_priv | pii_basic | `http:GET /api/StoredFile/FilesList` | RC-sec-bola |
| H4 | Workflow-task assignment bypass | auth_bypass | low_priv | business | `http:GET …/Process/UserTaskDetails` | RC-sec-rt-trust |
| H5 | Personal-data entity lacks a `[GlobalSpecification]` | data_exposure_pii | any_authenticated | popia_special | `db:<Entity>` | RC-sec-no-rowfilter |

*(H5 static-absence is DET; "holds personal data" is ND — split into a DET per-entity "no spec" finding + the ND sensitivity judgement.)*

---

## I — Token & session policy. Capability: live + admin (I2 also static). Sub-area: SC.

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| I1 | Symmetric (HS*) signing alg | info_leak | local_only | none | `token:header.alg` | DET | RC-sec-token |
| I2 | Signing key too short / low-entropy | auth_bypass | anonymous | none | `<path>#key:Authentication:JwtBearer:SecurityKey` | DET | RC-sec-committed-secret |
| I3 | Token lifetime > 24h | auth_bypass | any_authenticated | none | `<path>#key:…TokenExpiration` | DET (static) / ND (live claims) | RC-sec-token |
| I4 | SignOff does not invalidate token | auth_bypass | any_authenticated | none | `http:POST /api/TokenAuth/SignOff` | **ND** (probe) | RC-sec-token |
| I5 | No refresh-token rotation | auth_bypass | any_authenticated | none | `sln:refresh-rotation=absent` | **ND** | RC-sec-token |

*I2 cross-refs `hardening-shesha-app` (the fix) and the **starter-key fingerprint** check (SEC-T, formerly SEC-P here) — one canonical id.*

---

## J — Rate limiting & lockout. Capability: static. Sub-area: AC (J3→RT).

| CHECK-ID | title | impact_class | reach | data_sens | anchor | DET/ND | root_cause |
|---|---|---|---|---|---|---|---|
| J1 | No rate limiter configured | dos | anonymous | none | `sln:rate-limiter=absent` | DET | RC-sec-dos |
| J2 | Lockout absent/weak | auth_bypass | anonymous | none | `sln:lockout=absent` | DET presence / **ND** "sensible value" | RC-sec-weak-auth |
| J3 | OTP / reset-flow burst unprotected | dos | anonymous | none | `http:POST …/Otp/SendPin` | **ND** (judgement probe) | RC-sec-dos |

*Fix: do **not** collapse J1+J2 into one verdict (current code fires only when all five patterns absent). Each is its own CHECK-ID.*

---

## K — Dependency advisories *(renamed from the `D1/D2` posture ids — ends the `D`-prefix collision)*. Capability: dotnet feed / npm. Sub-area: SC. **ND** (time-varying advisory DB; SKIP→`NOT-ASSESSED(no-tool)`).

| CHECK-ID | title | anchor | root_cause |
|---|---|---|---|
| K1 *(was `D1-dotnet-vulnerable`)* | Vulnerable NuGet package | `dep:nuget:<package>@<version>` | RC-sec-deps |
| K2 *(was `D2-npm-audit`)* | Vulnerable npm package | `dep:npm:<package>@<version>` | RC-sec-deps |

---

## New checks to add (the TLC reverse-flow adds these)

| CHECK-ID | title | impact_class | reach | data_sens | DET/ND | owner |
|---|---|---|---|---|---|---|
| SEC-A | Client/route id trusted as identity (BOLA, static) | auth_bypass | any_authenticated | pii_basic | **Roslyn** (DET via analyzer) | auditing detect → access-control fix |
| SEC-H | POPIA personal data in a log call | data_exposure_pii | admin_only | popia_special | **Roslyn** (DET via analyzer) | auditing |
| SEC-U | Orphaned / unused permission (granted to no role, or required by no endpoint) | maintainability | local_only | none | DET | auditing detect → access-control fix |
| SEC-B | Single-record endpoint without the list's scope (IDOR), incl. StoredFile download; PII entity `GetAll` with no global specification | data_exposure_pii | any_authenticated | pii_basic | CODE-ONLY static + **ND** (two-principal probe) | auditing detect → access-control fix |
| SEC-C | Default permissions / "any authenticated": `DefaultEndpointAccess`, authorize ratio, open sensitive-entity CRUD, configuration-tamper endpoints | auth_bypass | any_authenticated | popia_special | DET (ratio grep) + **ND** (live default) | auditing detect → access-control fix |
| SEC-D | Anonymous endpoints and developer surfaces (Elmah, Swagger, Playground, Hangfire) not on the allow-list | info_leak | anonymous | none | DET (registration) + **ND** (probe) | auditing detect → hardening fix |
| SEC-E | Secrets in the working tree or history (gitleaks + seam grep), committed dumps, shared test credentials | data_exposure_pii (secret_exposure) | any_authenticated | none | DET (seam grep) + **ND** (history scan) | auditing detect → hardening fix |
| SEC-I | Settings endpoints: anonymous `Settings/GetValue` returning secret settings (run first; urgent stop) | data_exposure_pii (secret_exposure) | anonymous | none | VERIFIED-ARTEFACT (decompile) + **ND** (probe) | auditing |
| SEC-K | Business-flow security: status-write, client-chosen route, literal guard, HTTP-GET mutation, test endpoint, TOCTOU (each its own finding) | auth_bypass | any_authenticated | business | **ND** (probe + semantic) | access-control |
| SEC-L | Mass assignment / over-posting of protected fields | data_integrity | any_authenticated | business | DET (AutoMapper grep) | access-control |
| SEC-M | Unrestricted file upload and import parsing (M1–M5: allow-list, size, filename, web root, zip-slip / XXE / decompression bomb) | data_integrity | any_authenticated | none | DET (static) | auditing |
| SEC-V *(was SEC-M here)* | Mass-import endpoint unguarded | auth_bypass | any_authenticated | business | DET (catalogue) | auditing |
| SEC-F | SignalR / real-time hub without auth or with client-chosen groups | data_exposure_pii | anonymous | pii_basic | DET (static) + **ND** (connect probe) | auditing |
| SEC-G | Injection & unsafe input (XSS / XXE / deserialization / open-redirect / HQLi / CSV), per-vector | data_exposure_pii | any_authenticated | pii_basic | DET (per-vector static) | auditing |
| SEC-J | Message consumer trusts message content as input (EasyNetQ / MassTransit) | data_integrity | any_authenticated | business | DET (static) | auditing |
| SEC-N | SSRF — outbound target from request / entity / user-editable setting, no allow-list or private-range block | info_leak | any_authenticated | none | DET (static) + **ND** (probe) | auditing |
| SEC-O | Security headers, CSP, HSTS, CORS, CSRF, cookie flags, production source maps (O1–O7; static rows A1–A3, A6–A8, B3) | info_leak (O2: auth_bypass) | anonymous | none | DET (static) + **ND** (header probe) | auditing detect → hardening fix |
| SEC-P | JWT validation settings: issuer, audience, lifetime, algorithms, rotation, revocation (static rows I1, I3–I5) | auth_bypass | anonymous | none | DET (static) + **ND** (`--deep` forge) | auditing detect → hardening fix |
| SEC-Q | GraphQL data plane bypasses authorisation (no per-field auth, introspection, no depth limit) | auth_bypass | anonymous | none | DET (static) + **ND** (query probe) | auditing |
| SEC-R | Background-job trust: trigger endpoint without a named permission; Hangfire `TypeNameHandling != None` | data_integrity | any_authenticated | business | DET (static) + **ND** (probe) | auditing |
| SEC-T *(was SEC-P here)* | Starter JWT key identical across Shesha systems (forgeable) | auth_bypass | anonymous | none | DET (fingerprint list) | auditing detect → hardening fix |
| SEC-S | Tenant isolation absent | data_exposure_pii | any_authenticated | popia_special | **ND** | access-control |
| INV-CHK | Inverse permission-checker (`default: return false` voids all grants) | auth_bypass | any_authenticated | business | DET (grep) + ND (grants-have-effect probe) | auditing detect → access-control fix |
| SEC-FW | Framework / ABP / Enterprise entity reachable through generic dynamic CRUD (or the generic `Entities` gateway) signed out or as a low-privilege user | data_exposure_pii | anonymous \| low_priv | pii_basic | **ND** (probe: `framework-entity-crud` sweep; DET once the entity-action records are captured) | auditing detect → access-control fix |
| SEC-ESC | A non-admin role can change an administrator's credentials, sign-in name, recovery email or mobile, security answers, roles or tokens | auth_bypass | low_priv | popia_special | **ND** (live per-role probe on a restorable copy) | auditing detect → access-control fix |
| SEC-DRIFT | A framework upgrade widened a built-in endpoint's effective requirement (opened the access level, or OR-ed in a permission a non-admin role holds) | auth_bypass | low_priv | business | **ND** (two captures + `drift.py`; DET once both are captured) | auditing detect (upgrade-shesha-stack runs it) → access-control fix |
| SEC-RESET | A custom permission record does not survive start-up (the framework hard-codes or re-applies it, or the record disappears) | auth_bypass | low_priv | business | **ND** (restart + `drift.py`) | auditing detect → access-control fix |
| SEC-GONE | A form or coded screen calls an endpoint the running version no longer serves | dos | any_authenticated | none | DET (form/front-end scan vs live surface) + **ND** (admin probe) | auditing detect → forms fix |

*SEC-ESC is rated with `popia_special`: an administrator account reaches every personal
record, so a takeover is Critical even though the attacker needs a low-privilege login.
SEC-FW, SEC-ESC, SEC-DRIFT, SEC-RESET and SEC-GONE are specified in
`references/reaudit-and-upgrade-drift.md`; each was missed by a first audit and found by a
post-merge re-audit. Root cause for SEC-DRIFT and SEC-RESET: `RC-sec-upgrade-drift`; SEC-FW
and SEC-ESC: `RC-sec-no-authz`; SEC-GONE: `RC-sec-upgrade-drift`.*

**Coverage record, not a check: `COV-BRANCH`.** A module or product that lives only on a
branch the audit did not cover is recorded in `_index.json` `inputsMissing` and the report as
`NOT-ASSESSED(branch-not-audited)` with the branch name. It is never scored and never silently
dropped (`reaudit-and-upgrade-drift.md` section 1).

**Full detection specs:** `references/security-checks.md` (INPUT / PREDICATE / ANCHOR / EVIDENCE / REMEDIATION / REGRESSION / SEVERITY per check) for SEC-B, C, D, E, F, G, I, J, K, L, M, N, O, P, Q, R and S, with the `PLAN-SEC-*` templates and named regression tests. SEC-A and SEC-H: the Roslyn analyzer. SEC-FW, ESC, DRIFT, RESET, GONE: `reaudit-and-upgrade-drift.md`.

**One ID scheme.** The SEC letters keep the TLC meanings the conductor, `shared/operating-standard.md` and the inspector briefs use. Two registry rows that clashed were renumbered: starter JWT key fingerprint **SEC-P → SEC-T**; mass-import endpoint unguarded **SEC-M → SEC-V**. A SEC check is an umbrella; when a fine-grained registry row (A–K) fits, the finding takes that id (map in `security-checks.md`, "Catch-up").

**Root causes for the restored checks:** SEC-B `RC-sec-bola`; SEC-C, SEC-Q `RC-sec-no-authz`; SEC-D `RC-sec-starter-surface`; SEC-E, SEC-T `RC-sec-committed-secret`; SEC-I `RC-sec-anon-settings`; SEC-K, SEC-R `RC-sec-rt-trust`; SEC-L, SEC-M, SEC-V `RC-sec-input-integrity`; SEC-O `RC-sec-headers` / `RC-sec-cors`; SEC-P `RC-sec-token`; SEC-S `RC-sec-no-rowfilter`.

---

## Decisions this registry bakes in (flag if you disagree)

1. **Prefix-collision fixes:** `G1-secrets` → **B7**; dependency `D1/D2` → **K1/K2**. (The current code's first-letter grouping in `verify_run.py`/`merge_findings` mis-buckets these.)
2. **Severity-mismatch fixes:** A3 **Critical** only as wildcard+credentials (A2+A3); D5 solution-wide **Medium** tally vs the per-entity **H5 High**; J3 **High**.
3. **DET vs ND split:** only the ~18 DET checks enter the byte-identity acceptance diff now; the ND ones carry `non_deterministic:true` until the Roslyn analyzer (SEC_A/H, C5) and probe-result normalization land. This is honest, not a downgrade.
4. **SEC-N is now defined** (SSRF) and added, alongside the other previously-missing detection checks **SEC-F** (SignalR), **SEC-G** (injection) and **SEC-J** (message-consumer input surface) — full specs in `references/security-checks.md`. This closes the detection gaps found by comparing the standalone skill against TLC's `checks/security.md`.
5. **One SEC ID scheme (catch-up from the 3 Nov modularisation).** The SEC letters keep the TLC meanings (conductor, operating standard, briefs). Registry rows that clashed were renumbered: starter JWT key **SEC-P → SEC-T**, mass import **SEC-M → SEC-V**. SEC-O is no longer "covered": it is the umbrella for O1–O7 with A1–A3/A6–A8/B3 as its static rows. Two root causes were added to the closed set: `RC-sec-anon-settings`, `RC-sec-input-integrity`.
