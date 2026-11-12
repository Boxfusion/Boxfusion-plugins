# Security checks — detection specs ported from the TLC security division

Full detection specifications for the security checks that the catalogue, probes and analyzer do not already cover. Registered in `check-registry.md`; the determinism contract (`determinism-standard.md`) governs ids, evidence, severity and output exactly as for every other check. Each finding id is `CHECK-ID@<anchor>` — no ordinal; N anchors ⇒ N findings.

SEC-F, SEC-G, SEC-J and SEC-N were the first detection gaps flowed back from TLC. The rest of the TLC SEC set (SEC-B, C, D, E, I, K, L, M, O, P, Q, R, S), lost in the 3 Nov modularisation, is restored under "Catch-up" below, with the route-prefix rules, capability gating, fixed severity inputs and `--deep` closers. SEC-A and SEC-H are decided by the Roslyn analyzer (`resources/analyzers/`). SEC-FW, SEC-ESC, SEC-DRIFT, SEC-RESET and SEC-GONE are in `reaudit-and-upgrade-drift.md`.

---

## SEC-G — Injection & unsafe input

Per-vector predicate; emit a verdict line for each vector even when empty (e.g. `SEC-G@xss=none`), so a clean system is provably clean, not silently unchecked.

- **INPUT / PREDICATES (per vector):**
  - **XSS** → `dangerouslySetInnerHTML` / Razor string-concatenation into markup.
  - **XXE** → `XmlReader` / `XmlDocument` / `LoadXml` without `DtdProcessing.Prohibit` **and** a null `XmlResolver`.
  - **Unsafe deserialization** → `TypeNameHandling != None` / `BinaryFormatter` / `LosFormatter`.
  - **Open redirect** → `Redirect(var)` / a `returnUrl` used without `Url.IsLocalUrl`.
  - **HQL injection** (the Shesha-native SQLi analogue) → `CreateQuery(` / `session.CreateQuery` built with `+` or string interpolation.
  - **CSV / formula injection** → an export writing cell values without a `'`-prefix / escaping.
  - **LDAP / OS-command**, **ReDoS**, **SSTI** → the usual sink patterns with an untrusted argument.
- **VERDICT / ANCHOR:** a finding per hit at `SEC-G@<vector>@<path>#<symbol>`; otherwise `SEC-G@<vector>=none`.
- **EVIDENCE:** `CODE-ONLY` static; `REPRODUCED` where a live probe fires the vector.
- **REMEDIATION `PLAN-SEC-G`** (per vector): encode on render; parameterised HQL via `SetParameter`; `TypeNameHandling.None`; `Url.IsLocalUrl` allow-list; prefix-escape CSV cells; `DtdProcessing.Prohibit` + null resolver.
- **REGRESSION TEST:** `Injection_ParameterisedQueriesAndSafeRender_Test`.
- **SEVERITY:** stored XSS (`data_exposure × any_authenticated`) → High; reachable deserialization (`auth_bypass`/RCE) → Critical/High.

---

## SEC-N — SSRF (server-side request forgery)

`impact_class = info_leak` (SSRF-to-internal).

- **INPUT:** grep `new HttpClient`, `GetAsync` / `PostAsync`, `WebRequest`, `RestClient`, `FtpWebRequest` where the base address / URL is a **variable**; webhook / callback registration endpoints; settings-driven base URLs. Define a "locked" setting = **not** writable via `UpdateUserValue` / dynamic CRUD by a non-admin (test it).
- **PREDICATE:** the outbound target is sourced from (a request body / param) **or** (an entity field) **or** (a non-admin-writable setting) **AND** there is no host/scheme allow-list and no private-range block.
- **VERDICT / ANCHOR:** `SEC-N@<path>#<Type>.<Member>` (record the source: `request` | `entity` | `user-editable-setting`).
- **EVIDENCE:** `CODE-ONLY`; `REPRODUCED` needs a local listener + a running backend.
- **REMEDIATION `PLAN-SEC-N`:** allow-list hosts + schemes; resolve-and-validate the destination (block loopback / link-local / private ranges; re-validate after redirects or disable them); never let a user-editable setting supply an outbound base URL without the allow-list; set timeouts and response-size caps. Covers non-HTTP schemes (e.g. payroll FTP transfers), DNS-rebind / TOCTOU, and headless-renderer SSRF.
- **REGRESSION TEST:** `Ssrf_OutboundUrlAllowlistBlocksInternal_Test`.
- **SEVERITY:** two-step settings info_leak (`× low_priv`) → Low; request-driven internal fetch (`× any_authenticated`) → Medium.

---

## SEC-F — SignalR / real-time

`impact_class = data_exposure_pii / info_leak`.

- **INPUT / PREDICATES:**
  - **F1** a `Hub` / `AbpHubBase` subclass without `[Authorize]` → `SEC-F@<path>#<Hub>`.
  - **F2** a hub method reads a client-supplied value into `Groups.AddToGroupAsync` (client picks its own group) → finding.
  - **F3** decompile confirms the framework SignalR provider builds its `HubConnection` without an `accessTokenFactory` **and** targeted notifications are configured (grep the notification-channel config) → framework finding `SEC-F@pkg:…#SignalRProvider`, routed to the Shesha-team report.
- **EVIDENCE:** connect-anonymously is `REPRODUCED` but needs a backend → else `NOT-ASSESSED(no-backend)`; the static "no `[Authorize]`" is `CODE-ONLY`.
- **REMEDIATION `PLAN-SEC-F`:** authenticated hubs; server-computed groups from the user's own scope; send events only after commit; scrub tokens from logs; route the framework caveat to the Shesha-team report.
- **REGRESSION TEST:** `SignalR_HubRequiresAuthAndServerSideGroups_Test`.
- **SEVERITY:** a custom anonymous hub leaking scoped events (`data_exposure × anonymous`) → Critical; framework-caveat-only → Low.

---

## SEC-J — Message consumers as an input surface

`impact_class = data_integrity`. A background consumer processes attacker-influenceable messages; the message is **untrusted input** and must be validated and source-verified like any request. Distinct from **SEC-R** (which asks whether the consumer trusts *who triggered* it) — SEC-J asks whether it validates *what the message contains*.

- **INPUT / PREDICATE:** grep for consumer registrations across **both** common buses:
  - **EasyNetQ** (the BoxFusion default): `AddEasyNetQ`, `RabbitHutch.CreateBus`, `IBus`, `bus.PubSub.SubscribeAsync` / `bus.SubscribeAsync`, `IConsume<`, `[AutoSubscriberConsumer]`, `IAutoSubscriberConsumer`.
  - **MassTransit:** `IConsumer<`, `AddMassTransit`, `AddConsumer`.
  - None found → `SEC-J@none` (a deterministic empty verdict, not a skip). Otherwise, **per consumer:** it mutates state / fetches a URL / forwards a credential **AND** there is no source-signature or verification → `SEC-J@<path>#<Consumer>`. Also check: broker **default-host exposure** (ties the operations division, OPS-H), outbox / webhook receivers, and idempotency / replay handling.
- **EVIDENCE:** `CODE-ONLY` static.
- **REMEDIATION `PLAN-SEC-J`:** verify the message source / signature; validate the message content exactly like a request body; never take a URL or credential from a message without an allow-list (cross-reference SEC-N); use idempotency keys to defeat replay; guard broker defaults (no anonymous/default-host access).
- **REGRESSION TEST:** `MessageConsumer_SourceVerifiedAndValidated_Test`.
- **SEVERITY:** a consumer that creates users / mutates business state from **unsigned** messages on a **shared** broker (`data_integrity × any_authenticated`) → High; no consumers → no finding.

---

## Catch-up: the rest of the TLC SEC set

Restored from the TLC security division after the 3 Nov modularisation dropped them. **The
letters keep their TLC meanings**, which the conductor, `shared/operating-standard.md` and the
inspector briefs use. Two registry checks that clashed were renumbered: the starter-JWT-key
fingerprint is **SEC-T** (was SEC-P here) and "mass-import endpoint unguarded" is **SEC-V**
(was SEC-M here). Each SEC check is an umbrella; where the registry already has fine-grained
static rows, they are listed, and a finding takes the fine-grained id when one fits.

| SEC check | Registry rows it covers |
|---|---|
| SEC-B | H1, H2, H3, H5 |
| SEC-C | C1, C2, D1, D3, E1, E5, E7 |
| SEC-D | A4, A5, A10, A11, E2 |
| SEC-E | B1, B4, B5, B7, I2, SEC-T |
| SEC-O | A1–A3, A6–A8, B3, E8 |
| SEC-P | I1, I3, I4, I5 |
| SEC-R | C6 |

### Before any live probe

- **Pins (from the capability manifest):** `$SHA` is `$(SheshaVersion)` from
  `backend/Directory.Build.props`; `$DLL` is the `Shesha.Application/$SHA` path resolved from
  `Web.Host/obj/project.assets.json` (every decompile targets this exact path); `$BASE` is the
  backend URL when one is running.
- **Route prefix.** Custom-module app services are **not** under `/api/services/app/`. They are
  `/api/services/{moduleName}/...`, where `moduleName` is the `CreateControllersForAppServices(...,
  moduleName:)` argument in the module's `PreInitialize()`. Resolve it before probing; a guessed
  `/app/` path answers 404 and reads as "not reachable".
- **405 vs 404.** Send the wrong verb on purpose: 405 means the route exists, 404 means the path
  is wrong. Never record a 404 on a guessed route as a pass.
- **Without starting the app:** `Web.Host/obj/<config>/<framework>/ApiEndpoints.json` lists the
  routes; `ilspycmd` on `$DLL` shows anonymous attributes, default settings and custom checkers.
  **Read a validator or checker body before calling it empty:** validating input is not
  authorising the caller.

### Capability gating (an absent capability is a first-class NOT-ASSESSED, never a pass)

| Capability absent | Becomes `NOT-ASSESSED(reason)` |
|---|---|
| running backend | live dimension of SEC-I, SEC-D, SEC-O, SEC-F → `no-backend`; the static or decompile predicate still runs |
| low-privilege account | authenticated reachability of SEC-A, B, C, K, L, M, N → `no-low-priv-user` |
| gitleaks | SEC-E history and entropy recall → `no-secret-scanner`; seam-grep findings stand |
| git history (zero-commit repo) | SEC-E history → `zero-commit-repo`; the working-tree scan still runs |
| App Insights | SEC-H telemetry → `no-telemetry` |
| buildable backend | SEC-A and SEC-H analyzer → `SEC-A@analyzer` / `SEC-H@analyzer` `no-build` |

These fixed-anchor records are **mandatory**: every run emits each one that applies, always:
`SEC-C@sln:DefaultEndpointAccess`, `SEC-D@probe`, `SEC-E@scanner:gitleaks`, `SEC-H@telemetry`,
`SEC-K@forms`, `SEC-S@tenancy`. Empty verdicts (`SEC-x@none`, `SEC-G@<vector>=none`) and
NOT-ASSESSED records carry severity `Info`; they never enter the fix order.

---

## SEC-I — Settings endpoints (run first; a hit is an urgent stop)

Shesha 0.43.x–0.44.x `Settings/GetValue` can be called anonymously and return secret settings.
`impact_class = secret_exposure`, `data_sensitivity = secret`. Root cause `RC-sec-anon-settings`.

- **INPUT:**
  1. `ilspycmd -t Shesha.Settings.SettingsAppService $DLL`. Record the attribute on
     `GetValueAsync`, `GetValuesAsync`, `GetUserValueAsync`, `GetConfigurationsAsync`,
     `UpdateValueAsync`, `UpdateUserValueAsync`.
  2. Collect setting names matching
     `/(password|pwd|secret|key|token|clientsecret|connection ?string|apikey|dsn|smtp|credential)/i`
     from settings classes and configuration items.
  3. With a running backend: for each secret name,
     `GET $BASE/api/services/app/Settings/GetValue?Module={m}&Name={n}` with **no**
     Authorization header.
- **PREDICATE:** `GetValueAsync` carries `[AllowAnonymous]` AND (a probe returns 200 with a
  non-empty body for a secret name, OR no backend is running).
- **ANCHOR:** `SEC-I@pkg:Shesha.Application@$SHA#SettingsAppService.GetValueAsync`, plus one
  `SEC-I@http:GET /api/services/app/Settings/GetValue?Name={n}` per confirmed name (status,
  non-empty yes/no, length band; never the value).
- **EVIDENCE:** probe 200 → `REPRODUCED`; decompile only → `VERIFIED-ARTEFACT` on the attribute
  plus `NOT-ASSESSED(no-backend)` on the probe.
- **REMEDIATION `PLAN-SEC-I`:** an interim, case-insensitive gateway or middleware deny-filter on
  the secret-name pattern for the `Settings/GetValue` route (recorded as an emergency shortcut);
  honour each setting's `ClientAccess`; **rotate every exposed credential this release**; raise
  the framework defect with the Shesha team; ask IT whether production gateway logs show
  anonymous `Settings/GetValue` hits (precaution vs incident response).
- **REGRESSION TEST:** `Settings_GetValueSecretNamesDenied_Test` (anonymous GetValue for each
  secret name → 403/404; `UpdateUserValue` as low-priv → 403).
- **SEVERITY:** `secret_exposure × anonymous`, +secret → Critical.
- **Version note:** 0.43.34 / 0.44.2: `GetValueAsync` is `[AllowAnonymous]`, the others gated.
  0.45.1: `GetValueAsync` still anonymous, `GetConfigurationsAsync` regresses to anonymous and
  `UpdateValueAsync` loses `[SheshaAuthorize]`. Re-decompile `$DLL` every time; never assume a
  later release fixed it.

## SEC-C — Default permissions and "any authenticated"

`impact_class = auth_bypass`, `data_sensitivity` per entity. Root cause `RC-sec-no-authz`.

- **INPUT:**
  - Denominator `N`: unique app-service classes under `backend/src`, excluding `obj`, `bin` and
    test projects:
    `rg -No --type cs "class \w+AppService\b" backend/src | grep -vi "/obj/\|/bin/\|\.tests\?/" | sort -u | wc -l`.
  - Numerator `A`: the same set carrying `[AbpAuthorize("…")]` or `[SheshaAuthorize(…)]` with a
    permission name. Report plain `ControllerBase` counts separately.
  - `DefaultEndpointAccess`: live read only (`Settings/GetValue?Name=Shesha.Security` or the
    security settings screen). Do not decompile for it unless its type location is pinned.
  - Dynamic-CRUD entities carrying status, owner, tenant or personal-data fields; permissions
    named in attributes but never seeded; `requireAllPermissions:false`; a disabled tenant
    filter.
  - **Configuration-tamper endpoints**, always enumerated: `FormConfiguration/UpdateMarkup`,
    `PermissionedObject/Update`, `Permission/Create`, `ModelConfigurations`, `ReferenceList/*`.
- **PREDICATE:** `DefaultEndpointAccess ∈ {AnyAuthenticated(3), Disabled}` AND `A/N < 0.10` →
  the root-cause finding. Each sensitive entity whose CRUD record is **absent** (absent is open
  at the default, not locked) or has access 2 or 3 → one finding. If `N < 5`:
  `NOT-ASSESSED(too-few-services:N)`; a demo app is not "the whole system is unauthorised".
- **ANCHOR:** `SEC-C@sln:DefaultEndpointAccess={value}`, `SEC-C@sln:authorize-ratio={A}/{N}`
  (`VERIFIED-ARTEFACT`, a grep count), and per entity
  `SEC-C@http:PUT /api/dynamic/{Module}/{Entity}/Crud/Update`.
- **EVIDENCE:** live read of the default → `REPRODUCED`; without a backend the default is
  `NOT-ASSESSED(no-backend)` and the ratio stands. Authenticated reachability needs the
  low-privilege account (an anonymous 401 only proves the authenticated default exists).
- **REMEDIATION `PLAN-SEC-C`:** set `DefaultEndpointAccess = RequiresPermissions`; a named
  `[AbpAuthorize]` on every write or admin action; ship sensitive-entity CRUD permissions via the
  permissions manifest (not SQL); global specifications for row scope; implementation in
  `shesha-access-control`. A record set to RequiresPermissions with an **empty** permission list
  rejects everyone, admins included (E6).
- **REGRESSION TEST:** `AuthorizationInventory_NoInheritedOrAnyAuthenticated_Test`. It joins
  `EntityConfig.GetAll` with `PermissionedObject.GetAll`, drops `notImplemented:true`, and fails
  on any action that is absent or at access 2 or 3 and not on a reviewed allow-list. It is the
  named regression test of every SEC-A, B, C and K finding.
- **SEVERITY:** `auth_bypass × any_authenticated`, +1 band when special-category data is
  reachable → Critical.

## SEC-B — Single-record endpoints without the list's rules (IDOR)

`impact_class = data_exposure_pii`. Root cause `RC-sec-bola`.

- **INPUT:** every endpoint taking an id or natural key: `Get(id)`, PDF, report and download
  controllers, **`/api/StoredFile/Download?id=` and `DownloadZip`** (the most common Shesha
  IDOR), `GetByIds` / `GetList?ids=`, GraphQL `node(id:)`, lookups by phone or id number. Fixed
  enumeration so it always fires: `rg -n ": *ControllerBase|: *AbpController" --type cs`
  intersected with methods taking an id or natural key and returning a document or stream. For
  each, resolve the scope symbol it calls.
- **PREDICATE:** the list endpoint for entity `T` applies scope symbol `S`; the by-id endpoint for
  `T` does **not** call `S` and is not admin-permissioned. Also: a personal-data entity with a
  live CRUD `GetAll` and no registered `[GlobalSpecification]` →
  `SEC-B@http:GET /api/dynamic/{Module}/{Entity}/Crud/GetAll`.
- **ANCHOR:** `SEC-B@<path>#<Controller>.<Method>` ("list uses S, by-id does not"; record int
  vs GUID ids).
- **EVIDENCE:** `CODE-ONLY`; `REPRODUCED` needs the low-privilege account.
- **REMEDIATION `PLAN-SEC-B`:** apply the shared scope specification `S` on every by-id or by-key
  endpoint; answer **404** rather than 403 so ids cannot be enumerated; for `StoredFile`,
  authorise the owning entity before streaming.
- **REGRESSION TEST:** `Idor_ByIdEndpointsReturnNotFoundCrossScope_Test`.
- **SEVERITY:** `data_exposure_pii × any_authenticated` → High; +popia_special → Critical.

## SEC-K — Business-flow security (cross-area)

Each sub-predicate is its own finding; the Architect groups them at plan time, never at
authoring. Root cause `RC-sec-rt-trust`.

- **SUB-PREDICATES (one finding per hit):**
  - **status-write** `SEC-K@form:<module>/<name>`: a form script PUTs a generic `.../Crud/Update`
    whose body includes `requestStatus|status|ownerId|approverId|approve…` AND makes a separate
    `Process/UserTaskComplete` call. `data_integrity`.
  - **client-chosen route** `SEC-K@form:<module>/<name>#decisionUid`: `completeUserTask(todo,
    '<literal>')` passes a client-side literal or display-name-matched decision. `data_integrity`.
  - **literal guard** `SEC-K@<path>#<Type>.<Member>`: `if (<param> != "<literal>")` guards an
    integration action (record a length band only; if the repo is public, reachability is
    anonymous). `auth_bypass`.
  - **HTTP-GET mutation** `SEC-K@<path>#<Type>.<Member>`: an `[HttpGet]` action that mutates,
    sends or completes a step. `data_integrity`.
  - **test endpoint** `SEC-K@<path>#<Controller>.<action>`: a method whose name, enclosing
    `#region` or comment matches
    `/simulate|generate-?test|send-?test|#region Debug|testing purposes|for testing only/i`, on a
    `ControllerBase` or app service with no `[AbpAuthorize]`, touching an integration (file
    transfer, payroll, external gateway). A production generator without such a marker is not a
    test-endpoint finding. `auth_bypass`.
  - **TOCTOU** `SEC-K@<Type>.<Member>#toctou`: a state change done as two HTTP calls, not one
    unit of work, with no idempotency key.
  - Also: completing a task on a retired workflow version; generated-document actor or role not
    verified.
- **Classification is first-match, in this order** (it fixes `impact_class`): literal guard →
  test endpoint → HTTP-GET mutation → status-write.
- **EVIDENCE:** generic-CRUD reachability `REPRODUCED` via an anonymous 401 on its own anchor;
  form-script and code facts `VERIFIED-ARTEFACT`; authenticated reachability needs the
  low-privilege account. `SEC-K@forms` is the fixed record when forms could not be read.
- **REMEDIATION `PLAN-SEC-K`:** one app-service command per business action (save + status +
  task-complete in **one unit of work**, actor from the session via `GetLoggedInPersonAsync()`,
  route by a stable decision key, caller is the assignee and in the applicant's scope); generic
  CRUD rejects status, owner and approver fields (SEC-L); replace literal guards with
  `[AbpAuthorize("…")]`; environment-gate plus permission, or delete, every test, debug or
  simulate endpoint; row scope via a global specification.
- **REGRESSION TEST:** `BusinessFlow_StatusAndRouteServerEnforced_Test` (low-priv: status via
  generic CRUD rejected; completing an unassigned task → 403; a former literal-guard endpoint
  without permission → 403).
- **SEVERITY:** literal guard or test endpoint `auth_bypass × any_authenticated` → Critical;
  status-write or HTTP-GET mutation `data_integrity × any_authenticated` → High.

## SEC-D — Anonymous endpoints

`impact_class = info_leak`, or the stronger class of what the endpoint returns or does. Root
cause `RC-sec-starter-surface`.

- **INPUT:** grep `[AbpAllowAnonymous]` / `[AllowAnonymous]` (class and method); permissioned
  objects set to anonymous; plain `ControllerBase` with no `[Authorize]`. With a backend,
  request with no token: `/elmah`, `/elmah/api/errors`, `/ui/playground`, `/graphql`, `/swagger`,
  `/hangfire`, `/signalr-appender`. Find the playground with a **recursive** grep
  (`rg -n "ui/playground|GraphQLPlayground|UseGraphQLPlayground|MapGraphQL" backend/src --type cs`):
  `Startup.cs` is often two folders deep, and a shallow glob misses it.
- **Opening-move cross (required):** anonymous × (returns a secret or OTP, or mutates).
- **PREDICATE:** anonymous AND not on the allow-list {sign-in, OTP send/verify, token handshake,
  health}. A cross hit escalates `impact_class`.
- **ANCHOR:** one `CODE-ONLY` finding per developer endpoint registered in `Startup`
  (`SEC-D@http:GET /elmah`, `/swagger`, `/ui/playground`), plus the fixed `SEC-D@probe` record for
  live reachability. Never fold Elmah into the probe record.
- **EVIDENCE:** probe 200 → `REPRODUCED`. If `/elmah/api/errors` stores a live Bearer token,
  escalate to Critical (`--deep`).
- **REMEDIATION `PLAN-SEC-D`:** require authentication, or for genuinely public endpoints signed
  requests or API keys plus rate limits; webhooks verify the source signature and never act on an
  empty or unverified token; gate or strip `/elmah`, Swagger, the GraphQL Playground and Hangfire
  outside Development, and confirm the reverse proxy does not expose them. An un-rate-limited
  anonymous OTP endpoint is SMS bombing and enumeration: add rate limiting.
- **REGRESSION TEST:** `AnonymousSurface_OnlyAllowlistedEndpointsReturn200Anon_Test`.
- **SEVERITY:** `/elmah` or the Playground `info_leak × anonymous` → High; allow-listed health →
  no finding.

## SEC-E — Secrets

`impact_class = secret_exposure` (a JWT key is `auth_bypass`), `data_sensitivity = secret`. Root
cause `RC-sec-committed-secret`.

- **INPUT:**
  1. `gitleaks detect --source . --no-git` (working tree) and `gitleaks detect --source .`
     (history).
  2. Seam grep over configuration and code: `Password=|SecurityKey|ClientSecret|ApiKey|
     ConnectionString|BearerToken` in **all** `appsettings*.json` (including commented lines, and
     the working tree on zero-commit repos); per-partner `Integrations` blocks (flag
     `EnvironmentType:"LIVE"` beside a credential); module `.WithDefaultValue(` /
     `RegisterSettingAccessor` literals; `DangerousAcceptAnyServerCertificateValidator` /
     `ServerCertificateCustomValidationCallback => true`; CI pipelines, `docker-compose*`, helm
     `values*`, `launchSettings.json`; committed database dumps (`*.bacpac`, `*.backup`; SEC-E owns
     them); `NEXT_PUBLIC_*`; package-feed keys in `NuGet.Config` / `.npmrc`; mobile signing
     keystores and their passwords; map and push-notification keys.
  3. Count per-developer `appsettings.{Name}.json` files sharing one secret (a count, never the
     names).
  - "Long random string" means Shannon entropy ≥ 4.0 bits/char over ≥ 20 chars; otherwise defer
    to gitleaks. Known-empty allow-list: `string.Empty`, `""`, `changeme`, `<...>`.
- **PREDICATE:** gitleaks reports a finding (minus triaged false positives), OR a seam grep hits a
  literal not on the allow-list. If gitleaks is absent, emit `SEC-E@scanner:gitleaks`
  `NOT-ASSESSED(no-secret-scanner)` and report the grep as a spot-check, never as "clean".
- **ANCHOR:** `SEC-E@<path>#key:<json.path>`, with the key path **verbatim from the file** (never
  lowercased), plus presence and length band. A committed dump is `SEC-E@<repo-relative-path>`
  with no suffix. Shared test-environment credentials found in many files are **one** aggregate
  record, `SEC-E@credentials:shared-qa`, carrying the file count and the authoritative stores,
  not one record per file. Prove a match to deployed configuration by SHA-256 compare only.
- **EVIDENCE:** the committed-key fact is `VERIFIED-ARTEFACT`; forgeability is a `CODE-ONLY`
  inference.
- **REMEDIATION `PLAN-SEC-E`:** move to the pipeline or key vault; **rotate** (committed means
  compromised, history included); fail fast if unset outside Development; gitignore the
  per-developer `appsettings.{Name}.json` pattern; remove committed dumps from the repository
  **and its history**; turn on push protection and a gitleaks CI step. The same change carries
  the hand-over in `hardening-shesha-app` ("Moving a secret out of the repository").
- **REGRESSION TEST:** `SecretScan_GitleaksCleanTreeAndHistory_CI`.
- **SEVERITY:** JWT key `auth_bypass` × anonymous (public repo) or any_authenticated (private)
  → Critical; committed dump with special-category data → Critical; shared test credentials →
  High, or Low if confirmed not reused in production (`local_only`).

## SEC-O — Security headers, CSP, HSTS, CORS, CSRF, cookies and source maps

Sub-checks, each with its own anchor and severity. Root cause `RC-sec-headers` (O1, O3–O7) and
`RC-sec-cors` (O2).

- **INPUT:** back end: `Startup` and the pipeline for `UseHsts`, a security-headers middleware,
  `Headers.Add`, the CORS policy builder, antiforgery setup; with a backend, `curl -I` on
  `{/, an API route, /elmah, /swagger}`. Front end: `next.config.js` `headers()` and
  `productionBrowserSourceMaps`.
- **SUB-PREDICATES:**
  - **O1** `SEC-O@<path>#Startup.Configure`: no `UseHsts` and no security-headers middleware.
    `info_leak` → Low.
  - **O2** `SEC-O@<path>#Startup.Cors`: `SetIsOriginAllowed(_ => true)` (or a wildcard) with
    `AllowCredentials()`. `auth_bypass × anonymous` → Critical.
  - **O3** `SEC-O@<path>#csp`: a CSP containing `unsafe-inline` / `unsafe-eval`. → Low.
  - **O4** `SEC-O@next.config.js#headers`: no `headers()` block, or `productionBrowserSourceMaps:
    true` (source maps shipped to production). → Low.
  - **O5** `SEC-O@http:<route>`: a probed route returns 200 with **none** of
    `X-Content-Type-Options`, `X-Frame-Options` / `frame-ancestors`, `Strict-Transport-Security`.
    → Low.
  - **O6** `SEC-O@antiforgery`: a cookie-authenticated endpoint without
    `[ValidateAntiForgeryToken]` / `AutoValidateAntiforgeryToken` (JWT-bearer paths are exempt).
    → Low.
  - **O7** `SEC-O@cookies`: auth cookies without `Secure`, `HttpOnly` or `SameSite`; authenticated
    responses without `Cache-Control: no-store`. → Low.
- **EVIDENCE:** CORS proof: `Origin: https://evil.example.com` reflected in
  `Access-Control-Allow-Origin` with `Allow-Credentials: true` → `REPRODUCED`. Header presence
  needs a backend, else `NOT-ASSESSED(no-backend)` plus a `CODE-ONLY` static read.
- **REMEDIATION `PLAN-SEC-O`:** a security-headers middleware on the API and `headers()` in
  `next.config.js` (HSTS with subdomains, nosniff, Referrer-Policy, frame-ancestors /
  X-Frame-Options, Permissions-Policy; CSP report-only, then enforced); the configured
  `App:CorsOrigins` allow-list instead of `SetIsOriginAllowed(_ => true)`; no production source
  maps; Secure / HttpOnly / SameSite on auth cookies; antiforgery on cookie-auth endpoints.
- **REGRESSION TEST:** `SecurityHeaders_PresentAndCorsAllowlisted_Test`.

## SEC-L — Mass assignment / over-posting

`impact_class = data_integrity` (privilege escalation when a role or clearance field is
reachable). Root cause `RC-sec-input-integrity`.

- **INPUT:** the exact grep
  `rg -n "CreateMap<\w*Dto, *\w+>|\.ReverseMap\(\)|\[AutoMap" backend/src --type cs`; DTOs that
  inherit the entity or add nothing to `FullAuditedEntityDto`; app-service parameters typed as
  the entity; decompile the CRUD base to see which properties `Update` writes.
- **Protected fields:** `IsApproved|Status|requestStatus|TenantId|OwnerId|PersonId|RoleNames|
  <audit fields>|Price|SecurityClearance|IdentityNumber|settable Id`, plus collections and
  navigation properties.
- **PREDICATE:** a bindable path (DTO→entity map or entity-typed parameter) exposes at least one
  protected field, with no `ForMember(Ignore)` or validator excluding it. If no app service
  consumes the DTO, it is **latent** (reachability `local_only`). No match → `SEC-L@none`.
- **ANCHOR:** `SEC-L@<path>#<MappingProfile>` or `SEC-L@http:PUT /api/dynamic/.../Crud/Update`,
  with the protected field names and wired / latent.
- **EVIDENCE:** `CODE-ONLY`; `REPRODUCED` needs the low-privilege account.
- **REMEDIATION `PLAN-SEC-L`:** a narrow input DTO of caller-settable fields only; the server
  sets status, owner, tenant, approver and role from the session or the workflow; ignore rules on
  protected members; for sensitive dynamic CRUD, restrict it (SEC-C) and validate the mutable
  set in a Fluent validator.
- **REGRESSION TEST:** `MassAssignment_ProtectedFieldsIgnoredOnBind_Test` (low-priv create or
  update with `{"isApproved":true,"ownerId":<other>,"requestStatus":<x>}` → ignored, 400 or 403).
- **SEVERITY:** wired `data_integrity × any_authenticated` → High; latent → Medium.

## SEC-M — Unrestricted file upload and import parsing

`impact_class = dos` for size-only gaps; `data_integrity` once content type, path or parsing is
uncontrolled. Root cause `RC-sec-input-integrity`.

- **INPUT:** grep `IFormFile`, `IStoredFileService`, `SaveFile|UploadFile`, `Request.Form.Files`,
  `[DisableRequestSizeLimit]`, `Path.Combine(` with a user-supplied filename; enumerate **every**
  `*ImportAppServiceBase` (`rg -n ": *\w*ImportAppServiceBase"`) and anchor at its
  `StartImportAsync`. Read the controls per upload or import action.
- **SUB-PREDICATES (each absent control is its own finding, naming the control):**
  - **M1** no extension and content-type **allow-list** (a block-list is not an allow-list);
  - **M2** no size cap;
  - **M3** filename not sanitised for `..`, absolute paths or alternate data streams;
  - **M4** stored inside the web root;
  - **M5** the OOXML / zip parser (EPPlus, ClosedXML, NPOI, OpenXml) validates no entry path
    (**zip-slip**), leaves DTDs enabled (**XXE**), or caps no decompression (**decompression
    bomb**): `control=zip-slip|xxe|bomb`.
  - Also: double extensions; SVG or HTML served back (stored XSS).
- **ANCHOR:** `SEC-M@<path>#<Type>.<Member>` (`#<Type>.StartImportAsync` for imports).
- **EVIDENCE:** `CODE-ONLY`; `REPRODUCED` needs a backend and an upload.
- **REMEDIATION `PLAN-SEC-M`:** allow-list extensions and sniff the content type; cap size; a
  server-side storage name (never the client filename in the path); store outside the web root
  and serve through an authorised endpoint; parse office formats with XXE off, entry paths
  validated and decompression limits; malware scan where available.
- **REGRESSION TEST:** `FileUpload_RejectsDisallowedTypeOversizeTraversal_Test`.
- **SEVERITY:** size cap only, stored outside the web root → Low; content type unchecked and
  served from the web root, or zip-slip / XXE reachable → Medium to High.

## SEC-P — JWT validation settings

`impact_class = auth_bypass`, `data_sensitivity = secret`. Root cause `RC-sec-token`. SEC-E treats
the key as a committed secret; SEC-P checks how tokens are **validated**. Rotating the key does
not fix `ValidateAudience = false`.

- **INPUT:** `rg -n "TokenValidationParameters|ValidateIssuer|ValidateAudience|ValidateLifetime|
  ValidAlgorithms|RequireSignedTokens|RequireExpirationTime" backend/src --type cs`; the
  `Authentication:JwtBearer` block in appsettings.
- **PREDICATE (one finding per failing parameter):** `ValidateAudience = false`,
  `ValidateIssuer = false`, `ValidateLifetime = false`, no `ValidAlgorithms` allow-list, token
  lifetime > 24 h (I3), refresh tokens not rotated (I5), sign-off does not revoke (I4).
- **ANCHOR:** `SEC-P@<path>#<Type>.<Member>` (e.g. `#Startup.ConfigureTokenAuth`).
- **EVIDENCE:** `CODE-ONLY` (`VERIFIED-ARTEFACT` if decompiled); an `alg:none` or
  foreign-audience forge is `--deep` `REPRODUCED`.
- **REMEDIATION `PLAN-SEC-P`:** `ValidateIssuer`, `ValidateAudience`, `ValidateLifetime` = true;
  pin `ValidAlgorithms`; short lifetime, rotation and revocation (`hardening-shesha-app` fixes
  lifetime and sign-off).
- **REGRESSION TEST:** `Jwt_RejectsForeignAudienceAndNoneAlg_Test`.
- **SEVERITY:** unvalidated audience or issuer `auth_bypass × anonymous` → Critical; lifetime
  > 24 h → Medium.

## SEC-Q — GraphQL data-plane authorisation

`impact_class = auth_bypass`. Root cause `RC-sec-no-authz`. The `/graphql` data endpoint is a
second read path that may bypass `SheshaAuthorizationFilter` and reopen everything SEC-C closes.
SEC-D's Playground finding is the information leak; this is the data plane.

- **INPUT:** `rg -n "AddGraphQL|UseGraphQL|MapGraphQL|AddGraphQLPlayground|DocumentExecuter|ISchema"
  backend/src --type cs`; look for depth and complexity limits, an introspection gate and
  per-field authorisation.
- **PREDICATE:** a GraphQL endpoint exists AND (no depth or complexity limit, OR introspection on
  outside Development, OR no per-field authorisation).
- **ANCHOR:** `SEC-Q@http:POST /graphql`.
- **EVIDENCE:** `CODE-ONLY`; `--deep`: an anonymous or low-priv query of a personal-data entity
  that returns rows → `REPRODUCED`, Critical.
- **REMEDIATION `PLAN-SEC-Q`:** enforce the permission model in resolvers; turn introspection off
  in production; add depth and complexity limits.
- **REGRESSION TEST:** `GraphQL_RequiresPermissionAndLimitsDepth_Test`.
- **SEVERITY:** `auth_bypass × anonymous` → Critical (static only: High until probed).

## SEC-R — Background-job trust

`impact_class = data_integrity`, `data_sensitivity = business`. Root cause `RC-sec-rt-trust`.
Who may enqueue or trigger a `[ScheduledJob]`, and how job arguments are deserialised.

- **INPUT:** `rg -n "\[ScheduledJob|IBackgroundJobManager|\.Enqueue\(|RunTrigger|StartJob|EnqueueAll|
  RecurringJob" backend/src --type cs`; the Hangfire serializer settings, especially
  `TypeNameHandling`.
- **PREDICATE:** a job-trigger endpoint lacks a named `[AbpAuthorize]`, OR job arguments
  deserialise with `TypeNameHandling != None`.
- **ANCHOR:** `SEC-R@<path>#<Type>.<Member>` and
  `SEC-R@http:POST /api/services/app/ScheduledJob/RunTrigger`.
- **EVIDENCE:** `CODE-ONLY`; a `--deep` enqueue probe → `REPRODUCED`.
- **REMEDIATION `PLAN-SEC-R`:** `[AbpAuthorize]` on trigger endpoints; `TypeNameHandling.None`
  for Hangfire job arguments; run jobs under an explicit identity.
- **REGRESSION TEST:** `BackgroundJob_TriggerRequiresPermission_Test`.
- **SEVERITY:** `data_integrity × any_authenticated` → High; deserialisation reachable →
  Critical.

## SEC-S — Tenant isolation

`impact_class = data_exposure_pii`, `data_sensitivity = popia_special`. Root cause
`RC-sec-no-rowfilter`.

- **INPUT:** `rg -n "Abp\.TenantId|SetTenantId|DisableFilter\(.*MayHaveTenant|IMustHaveTenant|
  CurrentTenant" backend/src --type cs`; whether multi-tenancy is wired (`AbpMultiTenancy`,
  `MultiTenancyConfig`).
- **PREDICATE:** an app service or consumer reads `Abp.TenantId` from the request, OR calls
  `DisableFilter(AbpDataFilters.MayHaveTenant)` outside a host or admin path. No multi-tenancy
  wired → the fixed `SEC-S@tenancy` `NOT-ASSESSED(single-tenant)`.
- **ANCHOR:** `SEC-S@<path>#<Type>.<Member>`.
- **EVIDENCE:** `CODE-ONLY`; a `--deep` cross-tenant read → `REPRODUCED`.
- **REMEDIATION `PLAN-SEC-S`:** derive the tenant from the authenticated context only; never
  honour a request-supplied tenant; keep `MayHaveTenant` on (`shesha-access-control`, SEC-S).
- **REGRESSION TEST:** `Tenancy_NoCrossTenantRead_Test`.
- **SEVERITY:** `data_exposure_pii × any_authenticated`, +popia_special → Critical.

---

## Fixed severity inputs per check

`impact_class` and `data_sensitivity` are fixed properties of the check; reachability comes from
the gate. Author these exactly, so two operators compute the same band.

| Check | impact_class | data_sensitivity | typical reachability → band |
|---|---|---|---|
| SEC-I | secret_exposure | secret | anonymous → Critical |
| SEC-C authorize-ratio | auth_bypass | popia_special | any_authenticated → Critical |
| SEC-E JWT key | auth_bypass | secret | any_authenticated → Critical |
| SEC-E database dump | secret_exposure | popia_special | any_authenticated → Critical |
| SEC-E shared test credentials | secret_exposure | none | any_authenticated → High |
| SEC-O CORS (O2) | auth_bypass | none | anonymous → Critical |
| SEC-O headers (O1, O4, O5) | info_leak | none | anonymous → Low |
| SEC-D developer endpoint | info_leak | none | anonymous → High |
| SEC-B by-id document | data_exposure_pii | pii_basic | any_authenticated → High |
| SEC-K literal guard / test endpoint | auth_bypass | business | any_authenticated → Critical |
| SEC-K HTTP-GET mutation | data_integrity | business | any_authenticated → High |
| SEC-M size-only upload gap | dos | none | any_authenticated → Low |
| SEC-L mass assignment (latent) | data_integrity | popia_special | local_only → Medium |
| SEC-N settings-driven outbound | info_leak | none | low_priv → Low |

## Overlap priority

First match wins; the losing check emits a one-line handover to the winner's `finding_id`, never
a duplicate: property authorisation → SEC-L; business flow or workflow (including test
endpoints) → SEC-K; endpoint authorisation → SEC-C / B / A; secret → SEC-E / I. A test endpoint
that also makes an outbound call is SEC-K, not SEC-N.

## `--deep` closers

When a backend, a low-privilege user and a restored database are all in the manifest, `--deep`
**must** run these; static operators are blind to them, and each upgrades its finding from
`CODE-ONLY` to `REPRODUCED`:

- the live `DefaultEndpointAccess` read and an anonymous personal-data entity `GetAll` (SEC-C);
- the PermissionedObject collection per entity (SEC-C);
- a two-principal object-level `GetAll` and by-id test (SEC-B);
- `/elmah/api/errors` token capture, escalating SEC-D to Critical if a live Bearer token is
  stored;
- a GraphQL query of a sensitive entity (SEC-Q);
- an anonymous probe of every test, debug or simulate endpoint (SEC-K);
- the framework-entity sweep and the admin-takeover probe (SEC-FW, SEC-ESC;
  `reaudit-and-upgrade-drift.md`).

## Framework-defect candidates

Route to the Shesha-team report, and only after reproducing: SEC-I anonymous
`Settings/GetValue`; `DefaultEndpointAccess = AnyAuthenticated` as an insecure default; the
SignalR anonymous-handshake caveat. A hit on a framework table or behaviour is never a finding
against the system's own developers.

---

## Ownership & hand-off

- **auditing detects** every check in this file (it is the detection spec). Access-control fixes (SEC-B, C, K, L, S) belong to `shesha-access-control`; settings fixes (SEC-O, SEC-P lifetime and sign-off, SEC-E key moves) to `hardening-shesha-app`. SEC-F and SEC-J are `CODE-ONLY` static greps + decompile; SEC-N is a static grep with a reproduction path; SEC-G is per-vector static with optional live probing.
- **Fixes:** SEC-G, SEC-N and SEC-J remediations are code-level — they drop to findings for human / code remediation (never auto-applied), consistent with the division's handling of judgement-heavy security fixes. SEC-F's authenticated-hub change is likewise a reviewed fix; the framework caveat (F3) routes to the Shesha-team report.
