# Security checks — detection specs ported from the TLC security division

Full detection specifications for the security checks that the catalogue, probes and analyzer do not already cover. Registered in `check-registry.md`; the determinism contract (`determinism-standard.md`) governs ids, evidence, severity and output exactly as for every other check. Each finding id is `CHECK-ID@<anchor>` — no ordinal; N anchors ⇒ N findings.

These four were the detection gaps when the security hardening was flowed back from TLC into this skill: **SEC-F**, **SEC-G**, **SEC-J**, **SEC-N**. The rest of the SEC set is covered by the catalogue (A–K), the probe set, the Roslyn analyzer (SEC-A, SEC-H) and the registry rows.

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
- **REMEDIATION `PLAN-SEC-N`:** allow-list hosts + schemes; resolve-and-validate the destination (block loopback / link-local / private ranges; re-validate after redirects or disable them); never let a user-editable setting supply an outbound base URL without the allow-list; set timeouts and response-size caps. Covers non-HTTP schemes (e.g. PERSAL FTP), DNS-rebind / TOCTOU, and headless-renderer SSRF.
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
  - **EasyNetQ** (the BoxFusion default, e.g. pd-dispatcher): `AddEasyNetQ`, `RabbitHutch.CreateBus`, `IBus`, `bus.PubSub.SubscribeAsync` / `bus.SubscribeAsync`, `IConsume<`, `[AutoSubscriberConsumer]`, `IAutoSubscriberConsumer`.
  - **MassTransit:** `IConsumer<`, `AddMassTransit`, `AddConsumer`.
  - None found → `SEC-J@none` (a deterministic empty verdict, not a skip). Otherwise, **per consumer:** it mutates state / fetches a URL / forwards a credential **AND** there is no source-signature or verification → `SEC-J@<path>#<Consumer>`. Also check: broker **default-host exposure** (ties the operations division, OPS-H), outbox / webhook receivers, and idempotency / replay handling.
- **EVIDENCE:** `CODE-ONLY` static.
- **REMEDIATION `PLAN-SEC-J`:** verify the message source / signature; validate the message content exactly like a request body; never take a URL or credential from a message without an allow-list (cross-reference SEC-N); use idempotency keys to defeat replay; guard broker defaults (no anonymous/default-host access).
- **REGRESSION TEST:** `MessageConsumer_SourceVerifiedAndValidated_Test`.
- **SEVERITY:** a consumer that creates users / mutates business state from **unsigned** messages on a **shared** broker (`data_integrity × any_authenticated`) → High; no consumers → no finding.

---

## Ownership & hand-off

- **auditing detects** all four (this file is the detection spec). SEC-F and SEC-J are `CODE-ONLY` static greps + decompile; SEC-N is a static grep with a reproduction path; SEC-G is per-vector static with optional live probing.
- **Fixes:** SEC-G, SEC-N and SEC-J remediations are code-level — they drop to findings for human / code remediation (never auto-applied), consistent with the division's handling of judgement-heavy security fixes. SEC-F's authenticated-hub change is likewise a reviewed fix; the framework caveat (F3) routes to the Shesha-team report.
