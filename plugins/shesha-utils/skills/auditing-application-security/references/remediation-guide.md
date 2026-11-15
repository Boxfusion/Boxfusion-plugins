# Remediation Guide — the annexures for the recommendations report

Every recommendation in a `{package}-recommendations.md` file points at a section here. The
report says *what* to change and *why it matters*; this file says *how*, in enough detail
that a developer who has not read the rest of the audit can act on it.

Write for a junior developer. No security jargon: "anyone on the internet can read this
without logging in", not "unauthenticated IDOR on an unauthorised endpoint".

## Contents
- A. Requiring a login or a permission on an endpoint
- B. Requiring a permission on entity data (CRUD)
- C. Restricting which rows a user can see
- D. Turning off an endpoint or an entity API
- E. Fixing the web host (CORS, error pages, Swagger, headers)
- F. Secrets: moving them out and rotating them
- G. Login sessions, tokens and repeated attempts
- H. Permissions and roles that do nothing
- I. Forms and screens nothing opens
- J. Verifying a change actually took effect
- K. Related skills and reference material

---

## A. Requiring a login or a permission on an endpoint

**The one thing to understand first.** In Shesha, the code attribute is *not* what decides
access at runtime. Every endpoint has a `PermissionedObject` row in the database, and that row
decides. The attribute in code only seeds the row at startup. So there are two ways to change
access, and they behave differently:

| Route | Durable? | Use when |
|-------|----------|----------|
| Set the access level on the `PermissionedObject` row (admin UI, API, or a migration) | Yes, **unless** the row is `hardcoded` | The endpoint comes from a NuGet package, or you want the change live now |
| Change the attribute in source | Yes, and it re-seeds on every restart | The endpoint is in this repository |

A row whose access is still `Inherited` is re-written from code on every restart, and a row
with `hardcoded = true` is re-written every restart no matter what you set. Check
`authorizationRules.hardcoded` in the catalogue before promising that a UI change will stick.

### A1. In source, for an endpoint this repository owns

```csharp
using Shesha.Authorization;
using Shesha.Domain.Enums;

// Whole service: every action needs the permission.
[SheshaAuthorize(RefListPermissionedAccess.RequiresPermissions, "Leave-Balance-Manage")]
public class LeaveBalanceAppService : SheshaAppServiceBase
{
    // One action, tighter than the class.
    [SheshaAuthorize(RefListPermissionedAccess.RequiresPermissions, "Leave-Balance-Adjust")]
    public async Task AdjustAsync(AdjustLeaveBalanceInput input) { ... }

    // One action, deliberately open to any logged-in user.
    [SheshaAuthorize(RefListPermissionedAccess.AnyAuthenticated)]
    public async Task<LeaveBalanceDto> GetMyLeaveBalanceAsync() { ... }
}
```

Access levels, and what each one means to a caller:

| Level | Meaning |
|-------|---------|
| `AllowAnonymous` | No login needed. Only for login, password reset and genuinely public pages. |
| `AnyAuthenticated` | Any logged-in user, including one with no roles at all. |
| `RequiresPermissions` | Only users whose roles grant one of the listed permissions. |
| `Disable` | Returns 404 to everyone, and disappears from Swagger. |
| `Inherited` | Nothing decided; the global `DefaultEndpointAccess` setting applies. |

**Multiple permissions are OR, never AND.** `RequiresPermissions, "A", "B"` lets in anyone
holding either. To require both, write the second check in the method body.

**The permission has to exist and be granted.** A permission no role holds locks everyone
out including administrators. Create it in a migration, then grant it to a role:

```csharp
// In the module's Migrations/ folder, e.g. M20260901120000.cs
[Migration(20260901120000)]
public class M20260901120000 : Migration
{
    public override void Up()
    {
        this.Shesha().PermissionCreate("Leave-Balance-Adjust", "Adjust leave balances",
            "Users with this permission may correct an employee's leave balance.");
    }
    public override void Down() { }
}
```

If the helper is not available in the pinned framework version, create the permission through
the admin UI (Configuration → Permissions) and record in the report that it is a manual step.

### A2. Through configuration, for an endpoint a package owns

The endpoint's source is not in this repository, so the only lever is the row:

```
PUT /api/services/app/PermissionedObject/Update
{
  "object": "Shesha.UserManagements.UserManagementAppService@Create",
  "type":   "Shesha.WebApi.Action",
  "access": 4,
  "permissions": ["app:Configurator"]
}
```

Or in the admin UI: Configuration → Permissioned Objects → find the object → set Access.

**Do this in a migration, not by hand,** or it exists only in the database it was typed into
and the next environment is still open. If the row is `hardcoded`, configuration will not
hold: the remaining options are a reverse-proxy rule blocking the path and an upstream
request to the package maintainers. Say so plainly rather than recommending a change that
silently reverts.

### A3. Raising the global default

`Shesha.Security` → `defaultEndpointAccess` is the fallback for every endpoint with no
explicit setting, **including all entity CRUD**. Never leave it at `AllowAnonymous (5)`.
`AnyAuthenticated (3)` is the usual floor; `RequiresPermissions (4)` is stricter but breaks
every endpoint that has no permission configured, so move to it only after the sensitive
endpoints have explicit permissions.

---

## B. Requiring a permission on entity data (CRUD)

Entities that Shesha generates CRUD endpoints for are authorised at the *entity action*
level, not the service level. Set them per action so read can be broader than write:

```
PUT /api/services/app/PermissionedObject/Update
{ "object": "Shesha.Leave.Domain.LeaveRequest@Update",
  "type": "Shesha.Entity.Action", "access": 4,
  "permissions": ["Leave-Request-Manage"] }
```

Actions are `Get`, `Create`, `Update` and `Delete` (`GetAll` and `Query` map to `Get`).

Or in the entity configuration UI: Configuration → Entities → the entity → the per-action
permission fields. That writes the same rows.

**On Shesha 0.43.x the `Shesha.Entity` and `Shesha.Entity.Action` tables are usually empty**
because the provider that seeds them is inactive. That is why so many entities resolve
through `defaultEndpointAccess`: there is no row to inherit from. Creating rows explicitly
for the entities that hold personal data is the single highest-value change in most
applications.

---

## C. Restricting which rows a user can see

A permission answers "may this user call this URL". It does **not** answer "may this user see
this row". If an employee can call `GetAll` on leave requests and gets everybody's leave
requests, no permission change fixes that — you need a specification.

```csharp
using Shesha.Specifications;

[GlobalSpecification]                       // applied to EVERY query for this entity
public class OwnLeaveRequestsOnly : ShaSpecification<LeaveRequest>
{
    public override Expression<Func<LeaveRequest, bool>> BuildExpression()
    {
        var personId = AbpSession.UserId == null
            ? Guid.Empty
            : GetCurrentPersonId();
        return r => r.Employee.Id == personId;
    }
}
```

Points that matter in practice:

- `[GlobalSpecification]` applies to every query for that entity, including dynamic CRUD,
  the generic `Entities` gateway and Excel export. Without the attribute it only applies when
  a caller asks for it, which an attacker will not.
- A supervisor usually needs their team's rows too, so the expression is normally "mine, or
  my subordinates'", not just "mine".
- An action that legitimately needs the unfiltered set uses `[DisableSpecifications]` on that
  one method — and every use of it is worth a comment saying why.
- Verify with two accounts. As an administrator every row is legitimately yours, so a
  specification that does nothing looks identical to one that works.

For the full pattern set, invoke the `shesha-developer:shesha-specifications` skill; it
scaffolds the class, the registration and the tests.

---

## D. Turning off an endpoint or an entity API

Prefer restricting to disabling wherever any caller is plausible. Restricting fails visibly
as "you do not have access" (403) and is reversible; disabling returns "not found" (404) and
looks like a bug to whoever hits it.

**An entity's whole API:** set `Access = 1 (Disable)` on the `Shesha.Entity` row and on each
`Shesha.Entity.Action` row. Also record the intent in source so a fresh database matches:

```csharp
[Entity(GenerateApplicationService = GenerateApplicationServiceState.DisableGenerateApplicationService)]
public class LeaveBalanceAuditItem : FullAuditedEntity<Guid> { ... }
```

**Verify the flag actually works on your framework version.** In several versions the
dynamic controller registration ignores `GenerateAppService`, so the endpoints stay live and
only the `Disable` row closes them:

```bash
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/dynamic/{module}/{Entity}/Crud/GetAll?maxResultCount=1"
```

**A single endpoint:** set the `Shesha.WebApi.Action` row named
`{ClassFullName}@{MethodName}` to `Access = 1`.

**Do it in batches by module, and write a migration** so the change reaches every
environment. Forty simultaneous changes are impossible to attribute when a screen breaks.

---

## E. Fixing the web host

These live in this repository's `Startup.cs` and `appsettings.json`, so they are always
fixable here — the framework version is irrelevant.

### E1. CORS that allows any website (the most common real finding)

```csharp
// WRONG - any website can call this API using a logged-in user's session
app.UseCors(x => x
    .AllowAnyMethod().AllowAnyHeader()
    .SetIsOriginAllowed(origin => true)
    .AllowCredentials());

// RIGHT - only the origins this application actually serves
var corsOrigins = _appConfiguration["App:CorsOrigins"]
    .Split(",", StringSplitOptions.RemoveEmptyEntries)
    .Select(o => o.Trim().TrimEnd('/'))
    .ToArray();

app.UseCors(x => x
    .WithOrigins(corsOrigins)
    .AllowAnyMethod().AllowAnyHeader()
    .AllowCredentials());
```

Then check `App:CorsOrigins` is populated in every environment's settings and contains no
`*`. A wildcard origin combined with `AllowCredentials()` is the worst case: a user who is
logged in to your application and visits any other site can have their session used against
your API.

### E2. The error log served to anonymous callers

`app.UseSheshaElmah()` mounts the ElmahCore error log as middleware, which sits *outside*
the MVC pipeline — so Shesha's authorization filter never runs for it. Stored errors include
the full request headers, which means live `Bearer` tokens. Anyone who finds `/elmah` can
read them and use them.

```csharp
if (_env.IsDevelopment())
{
    app.UseSheshaElmah();
}
```

Two steps, both needed: close the path, **and rotate the JWT signing key** — the tokens
already captured in the store stay valid until the key changes.

### E3. Swagger and the GraphQL playground

```csharp
if (_env.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI(...);
    app.UseGraphQLPlayground(...);
}
```

Swagger is a map of every endpoint; the playground is an interactive query console. Neither
belongs in production. If Swagger is needed in a test environment, gate it on the
`SwaggerUiEnabled` setting instead of the environment.

### E4. Response headers

```csharp
app.UseSecurityHeaders();       // framework defaults: X-Frame-Options, X-Content-Type-Options
app.UseHsts();                  // production only
// The framework sets no Content-Security-Policy. Add one:
app.Use(async (context, next) =>
{
    context.Response.Headers["Content-Security-Policy"] =
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'";
    await next();
});
```

Start the CSP in report-only mode (`Content-Security-Policy-Report-Only`) if the front-end
has inline scripts, then tighten. A CSP that breaks the application gets deleted.

### E5. The Hangfire dashboard

`app.UseHangfireDashboard()` with no authorization filter lets anyone trigger or delete
background jobs. Pass an `IDashboardAuthorizationFilter` that requires an authenticated
administrator, or gate the whole call on the environment.

---

## F. Secrets: moving them out and rotating them

A key committed to git is compromised the moment anyone clones the repository, and deleting
the line does **not** help — git history keeps it. Two steps, in this order:

1. **Rotate**: generate a new value and set it in each environment's configuration (user
   secrets locally, environment variables or a key vault in deployed environments).
2. **Remove** the literal from tracked files, leaving the key present but empty so the shape
   of the configuration is still documented.

```jsonc
// appsettings.json - tracked
"Authentication": { "JwtBearer": { "SecurityKey": "" } }
```

```bash
# locally
dotnet user-secrets set "Authentication:JwtBearer:SecurityKey" "$(openssl rand -base64 48)"
```

Rotating the JWT signing key invalidates every issued token, so every user is logged out.
That is the intended effect when a key may have leaked; schedule it, do not spring it.

Judge key **strength** by entropy, not length: 32 random alphanumeric characters is about
165 bits and is not guessable. When the key is strong but committed, the finding is
*disclosure*, and the fix is rotation — do not describe a strong key as weak.

---

## G. Login sessions, tokens and repeated attempts

**Token lifetime.** A JWT cannot be revoked: it is valid until it expires, whatever the
"sign out" button does. So the lifetime is the length of time a stolen token keeps working.
Hours, not days.

```jsonc
"Authentication": { "JwtBearer": { "ExpireTimeSpan": "02:00:00" } }
```

**Account lockout** stops password guessing:

```csharp
Configuration.Modules.AbpZero().UserManagement.SmsVerification...   // varies by version
// Settings: Abp.Zero.UserManagement.IsLockoutEnabled = true
//           Abp.Zero.UserManagement.MaxFailedAccessAttemptsBeforeLockout = 5
//           Abp.Zero.UserManagement.DefaultAccountLockoutSeconds = 300
```

**Rate limiting** matters most where an endpoint that needs no login costs money or leaks
whether an account exists — OTP send, password-reset email and SMS:

```csharp
builder.Services.AddRateLimiter(options =>
{
    options.AddFixedWindowLimiter("otp", o =>
    {
        o.Window = TimeSpan.FromMinutes(1);
        o.PermitLimit = 3;
    });
});
app.UseRateLimiter();
```

Never test for the absence of rate limiting by running a burst of requests: it is
indistinguishable from an attack and, on a shared environment, disruptive. Read the
configuration.

---

## H. Permissions and roles that do nothing

Three distinct problems, three different fixes:

| Symptom in the catalogue | What it means | Fix |
|---|---|---|
| `isUnreferenced: true`, `rolesAssignedTo: []` | Dead configuration — nothing is guarded by it and nobody holds it | Delete it, or use it where it was clearly intended |
| Guards something, `rolesAssignedTo: []` | The guarded endpoint is unreachable by anyone | Grant it to the role that needs it, or lower the endpoint's access level |
| Roles hold it, guards nothing | Holding it grants nothing; users may believe they have access they do not | Attach it to the endpoints it was created for |
| `RequiresPermissions` with an empty permission list | Denies everyone, administrators included | Name the permission, or change the access level |
| A role with no permissions | Assigning it changes nothing | Configure its permissions, or remove the role |

Before deleting a permission, check nothing outside this repository references it — another
module's forms, or a deployment script.

---

## I. Forms and screens nothing opens

A form configuration with no menu entry, no other form referencing it and no coded screen
opening it is probably abandoned — but it is still **reachable by URL**, and if its access
level is `AllowAnonymous` it is reachable without logging in.

Order of preference:

1. If it is genuinely obsolete: delete the form configuration (and remove it from the
   `.shaconfig` package so it does not come back on the next import).
2. If you are not sure: set its `Shesha.Form` access to `RequiresPermissions` so a stray URL
   stops working, and revisit next release.
3. Never leave an unused form at `AllowAnonymous`.

The same applies to coded screens: a component nothing imports and no route renders is dead
code. Check it is not exported for another package before deleting it.

---

## J. Verifying a change actually took effect

Nothing is fixed until it has been re-tested. After each batch:

1. Restart the backend — several of these settings are re-seeded at startup, and one of them
   may re-seed the change away.
2. Call the endpoint with no token: expect 401.
3. Call it as a user who should not have access: expect 403.
4. Call it as a user who should: expect 200.
5. Exercise the screens that use the same entity — a wrongly disabled endpoint shows up as a
   broken table, not as an error in the log.
6. Re-run the catalogue phase and confirm the row now reads the way you intended.

Step 3 needs a second, low-privilege account. Without one, a change that appears to work may
simply be untested: as an administrator you pass every check.

---

## K. Related skills and reference material

In this repository:

| Need | Skill |
|------|-------|
| Row-level filters | `shesha-developer:shesha-specifications` |
| Migrations, entities, reference lists | `shesha-developer:domain-model` |
| Application services, DTOs | `shesha-developer:shesha-app-layer` |
| Settings accessors and defaults | `shesha-developer:shesha-settings` |
| Bulk-setting permissions through the admin UI | `shesha-utils:harden-permissions` |
| Inventory of shipped `.shaconfig` configuration | `shesha-utils:document-shaconfigs` |

In this skill:

| Need | File |
|------|------|
| How authorization is actually enforced at runtime | `references/enforcement-rules.md` |
| What this repository owns and can fix | `references/app-vulnerability-baseline.md` |
| Confirming a framework fix without framework source | `references/package-fix-matrix.md` |
| The safety gates before disabling anything | `references/disabling-unused-endpoints.md` |
| Field-by-field meaning of the catalogue JSON | `references/catalog-schemas.md` |

External reading, for a developer who wants the background:

- OWASP API Security Top 10 — <https://owasp.org/API-Security/editions/2023/en/0x11-t10/>
  (API1 Broken Object Level Authorization is section C above; API5 Broken Function Level
  Authorization is sections A and B)
- OWASP Cheat Sheets: Authorization, CORS, Content Security Policy, Secrets Management —
  <https://cheatsheetseries.owasp.org/>
- MDN on CORS and credentialed requests —
  <https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS>
- Shesha documentation — <https://docs.shesha.io/>
