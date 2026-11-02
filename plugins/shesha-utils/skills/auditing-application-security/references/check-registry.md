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

*Severity fix: D5 is **Medium** repo-wide (the per-entity "personal-data entity lacks a spec" is **H5 → High**). Resolves the baseline-MEDIUM vs code-HIGH mismatch by splitting the solution-wide absence (tally, Info-to-Medium) from the per-entity finding (H5).*

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

*I2 cross-refs `hardening-shesha-app` (the fix) and the **starter-key fingerprint** check (SEC-P) — one canonical id.*

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
| SEC-H | POPIA personal data in a log call | data_exposure_pii | n/a | popia_special | **Roslyn** (DET via analyzer) | auditing |
| SEC-K | Workflow self-approval / wrong-actor | auth_bypass | any_authenticated | business | **ND** (probe + semantic) | access-control |
| SEC-L | Property-level authz / over-posting | data_integrity | any_authenticated | business | **ND** | access-control |
| SEC-M | Mass-import endpoint unguarded | auth_bypass | any_authenticated | business | DET (catalogue) | auditing |
| SEC-N | *(to be defined from the TLC security division before porting)* | — | — | — | — | — |
| SEC-O | *(covered — folds into A1–A3/B3)* | — | — | — | — | — |
| SEC-P | Starter JWT key identical across Shesha systems (forgeable) | auth_bypass | anonymous | none | DET (fingerprint list) | auditing detect → hardening fix |
| SEC-R | Background-job / consumer trusts caller | auth_bypass | any_authenticated | business | **ND** (probe) | auditing |
| SEC-S | Tenant isolation absent | data_exposure_pii | any_authenticated | popia_special | **ND** | access-control |
| INV-CHK | Inverse permission-checker (`default: return false` voids all grants) | auth_bypass | any_authenticated | business | DET (grep) + ND (grants-have-effect probe) | auditing detect → access-control fix |

---

## Decisions this registry bakes in (flag if you disagree)

1. **Prefix-collision fixes:** `G1-secrets` → **B7**; dependency `D1/D2` → **K1/K2**. (The current code's first-letter grouping in `verify_run.py`/`merge_findings` mis-buckets these.)
2. **Severity-mismatch fixes:** A3 **Critical** only as wildcard+credentials (A2+A3); D5 solution-wide **Medium** tally vs the per-entity **H5 High**; J3 **High**.
3. **DET vs ND split:** only the ~18 DET checks enter the byte-identity acceptance diff now; the ND ones carry `non_deterministic:true` until the Roslyn analyzer (SEC_A/H, C5) and probe-result normalization land. This is honest, not a downgrade.
4. **SEC-N is undefined** in the branch — needs its definition from the TLC security division before it's added.
