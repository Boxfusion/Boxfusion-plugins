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
