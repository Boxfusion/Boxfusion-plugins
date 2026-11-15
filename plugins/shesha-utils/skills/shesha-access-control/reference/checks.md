# Access-control audit-mode decision procedure & remediation templates

This is the deterministic contract for the `access-control` sub-area: the decision procedure for the
checks this skill **decides**, and the remediation templates for every check it **remediates**. It
instantiates the shared standard; it does not fork it.

**Reuse, never redefine** (read these first, they are the single source of truth):
- `../auditing-application-security/references/determinism-standard.md` — the `findings.json` tuple
  `{ finding_id, anchor, evidence_level, severity, plan_id }`; the **evidence-level closed enum**
  (§3: `REPRODUCED > CONFIRMED-IN-LOGS > VERIFIED-ARTEFACT > CODE-ONLY > DATA-ANOMALY >
  NOT-ASSESSED(reason)` — MAX achieved per anchor); the severity function (§4); fix-order (§5);
  `root_cause` vocabulary (§6); NON-DETERMINISTIC quarantine (§7).
- `../auditing-application-security/references/check-registry.md` — the canonical **CHECK-IDs**, the
  **severity scoring key** (`base(impact_class, reachability)` shifted by `data_sensitivity`), the
  anchor forms, and each check's `root_cause`.

Every CHECK-ID, every `root_cause`, every severity below is **taken from** those files. The columns
here only add what this skill owns: the `plan_id` and the named regression test. Severity is shown
for orientation only — it is *derived* by the hub's scoring function from the three declared inputs
in the registry, never hand-set here.

---

## 1. What this skill decides vs. only remediates

- **Decides** (DET, enters the byte-identity acceptance diff): the static access-control checks a
  text/metadata scan can make reproducible — `access:4`-with-empty-permissions (E6), per-entity
  `[GlobalSpecification]` absence (H5/D5), orphaned/missing permission references, open dynamic-CRUD
  write nodes on a `generateAppService:true` entity (D3/D1). These are what the authorisation-
  inventory test's **static** invariants assert (no backend needed).
- **Only remediates** (ND until an instrument lands — see determinism-standard §7): the checks whose
  verdict needs a live probe or semantic analysis — SEC-A (Roslyn), C3/C4/C5, SEC-K, SEC-L, SEC-S
  live cross-tenant, INV-CHK grants-have-effect. This skill ships the fix template and the regression
  test; the **detection** stays in the hub / Roslyn analyzer / the inventory test's **live**
  invariants (gated on a low-priv account → else `NOT-ASSESSED`).

A check whose required capability is absent emits `NOT-ASSESSED(<reason>)` — first-class, never a
silent pass (determinism-standard §1).

---

## 2. Decision procedure

One row per access-control check. **INPUT** = what is read; **PREDICATE** = the total function that
decides; **VERDICT** = the evidence level emitted (from the §3 enum) when the predicate holds;
**ANCHOR** = the registry anchor form; **plan_id** = this skill's remediation template (§4);
**regression test** = the invariant/probe that proves the fix and prevents recurrence; **severity** =
derived by the scoring key (shown for orientation). `root_cause` is the registry's.

| CHECK-ID | INPUT | PREDICATE (holds ⇒ finding) | VERDICT | ANCHOR | plan_id | regression test | severity (derived) |
|---|---|---|---|---|---|---|---|
| **SEC-A** | Roslyn SEC_A result | a route/body id flows into a read/write without a session cross-check | CODE-ONLY (VERIFIED-ARTEFACT if build ran) | `<path>#<Type>.<Member>` | `AC-SEC-A-actor-from-session` | inventory INV-ACTOR + two-account IDOR probe | High (`auth_bypass` / any_authenticated, +pii_basic) |
| **C1** | service type metadata | no class-level `[AbpAuthorize]`/`[SheshaAuthorize]` and not on the public allow-list | CODE-ONLY | `<path>#<Type>` | `AC-SEC-C-permissioned` | inventory INV-PERMISSIONED | High |
| **C2** | member attributes | `[AllowAnonymous]` on an endpoint absent from the public allow-list | CODE-ONLY | `<path>#<Type>.<Member>` | `AC-SEC-C-permissioned` | inventory INV-PERMISSIONED (allow-list reason required) | Critical (anonymous) |
| **C5 / D1 / D4** | PermissionedObject + EntityConfig | entity read/write action reachable with no effective permission requirement | REPRODUCED (live) / CODE-ONLY (static) | `http:<VERB> /api/dynamic/<Module>/<Entity>/Crud/<op>` | `AC-SEC-C-permissioned` | inventory INV-CUD-CLOSED + low-priv probe | High |
| **D3** | EntityConfig.generateAppService + live surface | `generateAppService:true` and `@Create`/`@Update`/`@Delete` open (Inherited/empty) | CODE-ONLY decl / REPRODUCED probe | `<path>#<Type>` + `http:GET …/Crud/GetAll` | `AC-SEC-C-permissioned` | inventory INV-CUD-CLOSED | High |
| **E6** | PermissionedObject node | `access == 4` (RequiresPermissions) **and** `permissions == []` | VERIFIED-ARTEFACT | `dmv:permissionedobject:<record>` | `AC-SEC-C-permissioned` | inventory INV-NO-EMPTY-ACCESS4 | Medium (deny-all / `dos` admin_only) |
| **D5** | repo scan | zero `[GlobalSpecification]` classes anywhere | CODE-ONLY | `sln:global-specifications=0` | `AC-SEC-S-global-spec` | inventory INV-HAS-SPEC (tally) | Medium (solution-wide) |
| **H5** | entity + spec scan | a given entity has no `[GlobalSpecification]` and no reasoned exemption | CODE-ONLY absence / ND sensitivity | `db:<Entity>` | `AC-SEC-S-global-spec` | inventory INV-HAS-SPEC (per entity) | High (per-entity, +popia) |
| **ORPH-PERM** *(see §6 decision)* | PermissionedObject/code refs vs Permission catalog | a permission is referenced in code/PermissionedObject but is **absent** from the catalog, or a catalog permission is referenced by nothing | CODE-ONLY | `sln:orphaned-permission=<name>` | `AC-SEC-C-permissioned` | inventory INV-PERM-EXISTS | Medium (`maintainability`→auth_bypass if it guards a gate) |
| **SEC-K** | workflow transition + authorizer | approver can equal requester / wrong-actor transition | REPRODUCED (probe) | `http:<VERB> …/Process/<transition>` | `AC-SEC-K-sod-authorizer` | inventory INV-SOD + approver≠requester probe | High |
| **SEC-L** | DTO ↔ entity mapping | a write DTO lets a caller set a field they must not (over-posting) | CODE-ONLY | `<path>#<Type>.<Member>` | `AC-SEC-L-dto-allowlist` | inventory INV-OVERPOST + two-account field probe | High |
| **SEC-S** | tenant filter scan | no tenant global spec / cross-tenant read reproducible | CODE-ONLY absence / REPRODUCED live | `db:<Entity>` | `AC-SEC-S-global-spec` | inventory INV-TENANT + cross-tenant probe | High (+popia) |
| **INV-CHK** | custom-checker source + probe | a custom `ICustomPermissionChecker` `default`/fallthrough returns-not-false, **or** a granted non-admin is still denied | CODE-ONLY (grep) + REPRODUCED (grants-have-effect probe) | `<path>#<Type>.<Member>` | `AC-INV-CHK-default-false` | inventory INV-GRANTS-HAVE-EFFECT + grant/deny two-account probe | High |
| **SEC-FW** | `framework-entity-crud` probe results + `Shesha.Entity.Action` records | a package-owned entity's generic CRUD action answers a signed-out or role-less caller (OPEN / REACHED / NOT-FOUND) | REPRODUCED | `http:<VERB> /api/dynamic/<ns>/<Entity>/Crud/<op>` | `AC-SEC-FW-lock-framework-entity` | inventory INV-CUD-CLOSED extended to package entities + anonymous/role-less probe, before and after a restart | Critical (anonymous, identity/financial) / High |
| **SEC-ESC** | per-role live probe on a restorable copy (synthetic admin target) | a member of a non-admin role changed an administrator's password, sign-in name, recovery email/mobile, security answers, roles or tokens | REPRODUCED | `http:<VERB> <route>` + `role:<role>` | `AC-SEC-ESC-admin-credential-guard` | per-role takeover probe (403 and target unchanged) + guard unit tests | Critical (`popia_special`: an admin reaches everything) |
| **SEC-DRIFT** | `drift.py` old vs new build | a built-in record opened, or now also accepts a permission a non-admin role holds | VERIFIED-ARTEFACT (diff), then REPRODUCED (probe as that role) | `dmv:permissionedobject:<record>` | `AC-SEC-DRIFT-redesign-after-upgrade` | `drift.py` exit 0 on the next upgrade + per-role probe | High |
| **SEC-RESET** | `drift.py` first start vs restart | a custom record became hard-coded, changed, or disappeared across start-up | VERIFIED-ARTEFACT | `dmv:permissionedobject:<record>` | `AC-SEC-DRIFT-redesign-after-upgrade` | restart test: records identical after two starts + a unit test pinning the hard-coded assumption | High |

**Determinism rules the predicates obey** (so two runs agree byte-for-byte):
- Anchors are symbols/routes, never raw line numbers (determinism-standard §2); the inventory test
  lowercases the path part and strips `:\d+`.
- Output is **sorted** by `(severity_band, check_id, anchor)` and emitted as canonical
  `json.dumps(sort_keys=True, separators=(",",":"))` + trailing newline — the hub's normalizer owns
  this; the inventory test writes rows in that shape so the normalizer is a no-op.
- Evidence is never a severity input; an anonymous probe **is** REPRODUCED (§3).

---

## 3. plan_id catalogue

Templated, never free prose (determinism-standard §5). All `access-control` plan_ids are prefixed
`AC-`; the hub references them, this skill owns their content (§4).

| plan_id | Fixes | Regression test |
|---|---|---|
| `AC-SEC-A-actor-from-session` | actor derived from session, never a route/body id | INV-ACTOR + two-account IDOR probe |
| `AC-SEC-C-permissioned` | coverage: every action permissioned or allow-listed; bulk PermissionedObject apply + verify; no empty `access:4` | INV-PERMISSIONED, INV-CUD-CLOSED, INV-NO-EMPTY-ACCESS4, INV-PERM-EXISTS |
| `AC-SEC-K-sod-authorizer` | state-and-actor authorizer enforcing separation of duties (approver ≠ requester) | INV-SOD + approver≠requester probe |
| `AC-SEC-L-dto-allowlist` | write DTO allow-list / explicit field binding against over-posting | INV-OVERPOST + two-account field probe |
| `AC-SEC-S-global-spec` | tenant/owner `[GlobalSpecification]` (+ reasoned exemption register) | INV-HAS-SPEC, INV-TENANT + cross-tenant probe |
| `AC-INV-CHK-default-false` | inverse checker returns `false` by default + grants-have-effect probe | INV-GRANTS-HAVE-EFFECT + grant/deny two-account probe |
| `AC-SEC-FW-lock-framework-entity` | framework / ABP / Enterprise entity actions set to Disable (unused) or an admin-only permission, by migration | anonymous + role-less probe, first start and after restart |
| `AC-SEC-ESC-admin-credential-guard` | over-broad credential grants removed + code guard: only a System Administrator changes an admin's credentials | per-role takeover probe + guard unit tests |
| `AC-SEC-DRIFT-redesign-after-upgrade` | rules re-designed against the post-upgrade, post-start-up state; hard-coded records handled in code or by deliberate grants | `drift.py` (upgrade and restart) + pinning unit test |

---

## 4. Remediation templates

Each template is keyed to its registry id, carries its `plan_id`, and names its regression test. The
code is **illustrative** — verify the framework API shape against the target project's referenced
package version first (SKILL.md § Key Rules, "Verify the framework API shape"). SEC-K and SEC-L are
seeded from general secure-design practice because the branch has no source to derive them from.

### SEC-A — actor derived from the session, never a client/route id · `AC-SEC-A-actor-from-session`

**Root cause** `RC-sec-bola`. The endpoint trusts an id supplied by the caller (route segment, query,
or request body) as the identity it acts for. Fix: resolve the actor from the authenticated session
and ignore any caller-supplied actor id; scope the record to that actor (or re-check ownership).

```csharp
// WRONG — the caller tells us who they are
public async Task<ProfileDto> GetProfile(Guid personId)   // personId comes from the route/body
    => Map(await _repo.GetAsync(personId));

// RIGHT — actor comes from the session; a caller-supplied id is only ever an input to a check,
// never the identity. GetLoggedInPersonAsync() is the verified real helper (NOT the
// EnterpriseSessionBase.PersonId property — override-only, null for ordinary requests).
public async Task<ProfileDto> GetMyProfile()
{
    var me = await ResolveCurrentPersonIdAsync();         // throws/denies if no logged-in person
    return Map(await _repo.GetAsync(me));
}
// For an endpoint that legitimately targets another record, keep the id but re-check:
//   if (!await _authorizer.CanView(entity)) throw new AbpAuthorizationException(...);
```

**Regression test:** `INV-ACTOR` (static: no write/read method binds an actor from a route/body id
without an ownership re-check) **plus** a two-account IDOR probe — account A requests account B's
record by id and must be denied (`REPRODUCED` when the probe runs under a low-priv account; else
`NOT-ASSESSED(no-low-priv)`).

### SEC-C — coverage + bulk PermissionedObject apply with verify · `AC-SEC-C-permissioned`

**Root cause** `RC-sec-no-authz`. Every endpoint/entity action is permissioned **or** on the explicit
public allow-list with a reason. For dynamic-CRUD actions with no C# class, set the requirement via
`PermissionedObject/Update` (api-reference.md § PermissionedObject API) — `Create`/`Update`/`Delete`
get an explicit permission; leave `Get`/`GetAll` at Inherited **only when a verified spec protects
the rows** (SKILL.md § Step 4f). Apply in one batch, then re-fetch `PermissionedObject.GetAll` and
confirm every change landed (SKILL.md § Step 4i). Never leave an `access:4` node with an empty
`permissions` list (E6 — rejects everyone, including admins).

**Regression test:** `INV-PERMISSIONED` + `INV-CUD-CLOSED` + `INV-NO-EMPTY-ACCESS4` + `INV-PERM-EXISTS`
(inventory test, static — run with no backend). A low-priv probe upgrades the write-closed invariants
to `REPRODUCED`.

### SEC-K — state-and-actor authorizer: separation of duties · `AC-SEC-K-sod-authorizer`

**Root cause** `RC-sec-rt-trust`. A workflow transition must check **both** the state (is this
transition legal from the current status?) **and** the actor (is this a different person from the one
who created/submitted the record?). Seeded from secure-design practice: the approver must never be
the requester.

```csharp
public async Task<bool> CanApprove(MyRequest request)
{
    if (request.Status != RefListRequestStatus.Submitted) return false;   // state gate
    if (!await _permissionChecker.IsGrantedAsync("MyRequest-Approve")) return false;

    var approverId = await ResolveCurrentPersonIdAsync();
    // Separation of duties: approver != requester (and, where required, != last editor)
    if (request.CreatedByPerson?.Id == approverId) return false;
    return true;
}
```

**Regression test:** `INV-SOD` (static: every state-transition authorizer compares actor to the
record's originator) **plus** an approver≠requester probe — the requester account attempts to approve
its own record and must be denied.

### SEC-L — DTO allow-list / over-posting · `AC-SEC-L-dto-allowlist`

**Root cause** `RC-sec-no-authz` (property-level). A write DTO must expose **only** the fields the
caller may set; privileged fields (owner, tenant, status, approver, amount-after-approval) are set by
the server, never bound from the request. Seeded from secure-design practice.

```csharp
// WRONG — mapping the whole input onto the entity lets a caller set OwnerId/Status/TenantId
ObjectMapper.Map(input, entity);

// RIGHT — a narrow input DTO that cannot carry privileged fields, bound explicitly
public class UpdateMyRequestInput { public Guid Id; public string Title; public string Notes; }
entity.Title = input.Title;
entity.Notes = input.Notes;
// Owner, Status, Tenant set by server-side logic only — never from input.
```

**Regression test:** `INV-OVERPOST` (static: no write DTO exposes a privileged field name from the
privileged-field register) **plus** a two-account field probe — a non-privileged account posts a
privileged field and the persisted value is asserted unchanged.

### SEC-S — tenant/owner global specification + cross-tenant test · `AC-SEC-S-global-spec`

**Root cause** `RC-sec-no-rowfilter`. Every entity holding tenant- or person-scoped data has a
`[GlobalSpecification]` that filters rows to the caller's tenant/owner (or a **reasoned exemption** in
the exemption register — e.g. a genuinely global reference table). Use the verified-real synchronous
`BuildExpression()` pattern (implementation-patterns.md § "verified-real pattern").

```csharp
[GlobalSpecification]
public class MyEntityPermissionsSpecification : ShaSpecification<MyEntity>
{
    public override Expression<Func<MyEntity, bool>> BuildExpression()
    {
        if (AbpSession.UserId == null) return e => false;                 // default deny
        if (IocManager.Resolve<IShaPermissionChecker>()
                .IsGranted(AbpSession.UserId.Value, "MyEntity-View", null))
            return e => true;                                            // RBAC tier
        var me = ResolveCurrentPersonId();                                // owner tier
        return me == null ? (Expression<Func<MyEntity, bool>>)(e => false)
                          : (e => e.Owner != null && e.Owner.Id == me);
    }
}
```

**Regression test:** `INV-HAS-SPEC` (static, per entity) + `INV-TENANT` **plus** a cross-tenant probe
— an account in tenant A must not read a tenant-B row by id or see it in a list.

### INV-CHK — inverse `default: return false` + grants-have-effect probe · `AC-INV-CHK-default-false`

**Root cause** `RC-sec-no-authz`. A custom `ICustomPermissionChecker` must **decline by returning
`false`**, never by throwing (`NotImplementedException`) and never by returning `true` in a `default`
branch — either voids the whole RBAC-then-custom fall-through (SKILL.md § Key Rules). Fix every
overload to `return false` (or `Task.FromResult(false)`) by default.

```csharp
public override Task<bool> IsGrantedAsync(long userId, string permissionName)
    => Task.FromResult(false);   // decline cleanly — NOT throw, NOT true-by-default
```

**Regression test:** `INV-GRANTS-HAVE-EFFECT` (static: no checker overload throws or returns a
non-`false` default) **plus** a grant/deny two-account probe — a non-admin **granted** X is allowed X
(grants-have-effect) **and** a non-admin **not** granted X is denied X (and the request does not
crash). This is the only probe that catches the admin-invisible class of bug; it must run under a
low-priv account or it emits `NOT-ASSESSED(no-low-priv)`.

### SEC-FW: lock built-in entities exposed through generic CRUD · `AC-SEC-FW-lock-framework-entity`

**Root cause** `RC-sec-no-authz`. Framework, ABP and Enterprise entities (user accounts, user
roles and tokens, bank and financial accounts, settings and setting values, audit and change
logs, file templates, stored files, notes) get the same generic dynamic CRUD as app entities.
With no explicit record they follow the default endpoint access setting, which on some
systems is anonymous.

1. From the audit's `framework-entity-crud` results and the form, front-end and package-source
   scans, split the exposed entities into **unused** (no form, coded screen, framework or
   Enterprise screen, or integration calls them) and **used**.
2. **Unused: Disable** every action (`Get`, `Create`, `Update`, `Delete`). Disable answers 404
   to everyone, admin included. Confirm with the user first (SKILL Step 5 checklist).
3. **Used: admin-only.** `RequiresPermissions` with a permission only administrators hold
   (role management, or application settings for setting tables). Never an empty list (E6).
4. Ship it as a **migration** that writes the `Shesha.Entity.Action` records (object
   `<Full.Class.Name>@<Action>`), not as manual UI edits, so every environment gets it.
5. **Restart and re-probe** signed out, as a role-less user and as the admin. A record the
   framework hard-codes cannot be held by a migration; see SEC-DRIFT.

**Regression test:** the anonymous and role-less probes of every locked action, on first start
and after a restart; a unit test listing the locked entity actions, so a later migration cannot
silently reopen one.

### SEC-ESC: no non-admin path to an administrator's credentials · `AC-SEC-ESC-admin-credential-guard`

**Root cause** `RC-sec-no-authz`. A role that may manage *some* users, or edit staff records
synced to user accounts, can reach an administrator's account unless the target is checked.

1. **Remove grants a role does not need.** Credential permissions (password reset, user
   management) on front-line roles are often carried over from old permission names. Raise
   "must this role reset other users' passwords at all?" as a business question, defaulting
   to no.
2. **Add a guard in code** on every path that changes a user's password, sign-in name, recovery
   email or mobile, security questions or answers, password-reset methods, roles or tokens.
   That means framework endpoints (via an app-level filter or a wrapping service) **and** app
   services that sync person or staff changes to the user account:

```csharp
// Illustrative - verify the framework API shape for the target version (SKILL Key Rules).
if (await TargetHoldsAdministrativePermissionAsync(targetUserId)
    && !await CallerIsSystemAdministratorAsync())
    throw new AbpAuthorizationException(
        "Only a System Administrator may change the credentials of an administrator.");
```

   "Administrative permission" is a fixed list for the system (user and role management,
   application configuration and settings, the System Administrator role itself). Keep it in
   one place and unit-test it.
3. For sync services, either refuse the credential fields for privileged targets or stop
   syncing contact changes to the user account for them.

**Regression test:** the per-role takeover probe
(`../auditing-application-security/references/reaudit-and-upgrade-drift.md` section 3). Every
non-admin role gets 403 on every credential path against a synthetic administrator, and the
target is unchanged afterwards. A System Administrator still succeeds; a manager may still
reset an ordinary user if the business wants that. Add unit tests for the guard.

### SEC-DRIFT and SEC-RESET: design against the rules as they are after the upgrade · `AC-SEC-DRIFT-redesign-after-upgrade`

**Root cause** `RC-sec-upgrade-drift`. A framework upgrade can rename permissions, OR a second
permission into a built-in rule, remove records, and hard-code records. A hard-coded record
marks a service not configurable and re-applies its requirement at start-up; on a first
deploy that happens **after** the app's migrations.

1. Run `drift.py` old build vs new build on the same database copy, and first start vs restart
   of the new build.
2. For each `WIDENED` record: list the roles that now pass, probe as each, and either remove
   the grant from roles that should not pass or add a code guard (SEC-ESC for credentials).
3. For each `RESET` or `RECORD-GONE` record, configuration cannot hold it. Choose one, and say
   which: a code guard; granting the hard-coded permission deliberately (and reviewing who
   holds it, since a mis-named role holding user management becomes a hole); or a request to
   the framework team to make it configurable.
4. Add a unit test that pins the assumption (e.g. "this endpoint requires exactly X"), so the
   next upgrade fails a test instead of shipping silently.

**Regression test:** `drift.py` exits 0 on both comparisons, plus the per-role probes and the
pinning unit test.

---

## 5. Secret-safety note (applies to every doc, snapshot and script in this area)

Per determinism-standard §10: **never** put a token, password, connection-string password, API key,
JWT signing key or other secret into a design doc, a baseline/snapshot file, a `findings.json`, a
test fixture or any script committed here. When a check must record that a secret exists, record
**presence + length** or `sha256:<first-12-hex>` only — never the value. The inventory-test snapshot
stores check ids, anchors, verdicts and severities — it stores **no credential material**, and the
low-priv probe credentials are read from an un-committed config/secret store at run time, never
hard-coded. Findings name no person; see §6 for where framework flaws are routed.

---

## 6. Routing & open decisions

**Framework flaws → Shesha-team report (no-blame, determinism-standard §10).** These are defects in
the framework itself, not in any application's code, and must be routed to the Shesha-team report
rather than filed against an app or a person. They are documented in this skill only so a remediator
recognises them; the fix belongs upstream:
- **`EnterpriseSessionBase.PersonId` override-only** — the property reads an ambient "act-as" scope
  value, so it is `null` for every ordinary request; silently voids owner/ABAC checks. (api shape:
  SKILL.md § Key Rules, "Current Person".) Upstream ask: make the property fall back to the claims
  lookup, or mark it clearly non-general.
- **`Permission/Update` does not persist `Module`** — the module is set only in cache, so it reverts
  to NULL on restart and the permission cannot be exported (api-reference.md § Common Pitfalls #3).
- **`EntityConfig/Update` nulls `ModuleId`** — no known safe request body; worse than the Permission
  bug because it destroys an existing value (api-reference.md § Common Pitfalls #8, § EntityConfig
  API).

**Open decisions (flag to the user / hub):**
1. **ORPH-PERM has no dedicated CHECK-ID in the registry.** "Permission referenced but missing from
   the catalog" and "catalog permission referenced by nothing" are real access-control invariants
   (the inventory test asserts them), but the registry's "New checks to add" table does not name
   them. Proposed: register them (e.g. `SEC-Q` orphaned/missing permission) so the finding carries a
   canonical id rather than this skill's provisional `sln:orphaned-permission=<name>` anchor. Until
   then they emit under that provisional anchor and are marked `non_deterministic:false` but
   **registry-pending**.
2. **SEC-K/SEC-L predicates are seeded from secure-design practice**, not from branch source. When a
   real project is in scope, confirm the actual workflow-transition and DTO-mapping shapes before
   trusting the static predicate.
