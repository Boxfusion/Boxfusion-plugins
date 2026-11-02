# Check reference

One section per check: why it matters, what the scanner looks for, what the automatic fix
changes, how to fix it by hand when the fix can't, and how to prove it worked. Section numbers
are referenced from each check's `doc` attribute. Append new checks at the end, and never
renumber an existing section.

---

## Section 1. `token-lifetime`: JWT access token lifetime

**Why.** A JWT can't be recalled: it stays valid until its `exp`, whatever the user does.
Its lifetime is therefore how long a stolen token works: one lifted from a log, a
browser, a proxy or an error page. Shesha starter templates hard-code
`tokenAuthConfig.Expiration = TimeSpan.FromDays(n)`, often 1 to 5 days.

**Detection.** It finds `<x>.Expiration = ...;` in C# files that mention `TokenAuthConfiguration`
(normally `{Project}WebCoreModule.ConfigureTokenAuth`), and understands:

| Shape | Example |
|---|---|
| Literal | `TimeSpan.FromDays(5)`, `FromHours`, `FromMinutes`, `FromSeconds`, `new TimeSpan(h, m, s)` |
| Configuration-driven | anything reading `["Authentication:JwtBearer:<Key>"]`. The value is read from every `appsettings*.json` (a number means minutes, or a TimeSpan string such as `02:00:00` / `1.00:00:00`), plus a `: <n>` code fallback if present. |

Thresholds (options): FAIL above `fail_hours` (24), WARN above `warn_hours` (8), otherwise PASS.
There is also a note on whether the front end calls `/api/TokenAuth/RefreshToken`. If it does, a
short lifetime ends only idle sessions. If it doesn't, users are logged out mid-session when the
token expires, so agree the value with the product owner first.

**Automatic fix.**
- A literal becomes
  `TimeSpan.FromMinutes(int.TryParse(<config>["Authentication:JwtBearer:TokenLifetimeMinutes"], out var tokenLifetimeMinutes) ? tokenLifetimeMinutes : <minutes>)`,
  where `<config>` is the `IConfiguration` field the same file already uses. Each environment
  can then tune it in appsettings without a code change. If the file reads no configuration,
  it becomes `TimeSpan.FromMinutes(<minutes>)`.
- For a configuration-driven lifetime, the over-long appsettings values are rewritten in place,
  keeping comments and formatting.
- `minutes` defaults to 120. Override it with `--set token-lifetime.minutes=60`.

**Manual fix.** For an unrecognised expression, or an over-long code fallback, edit
`ConfigureTokenAuth` so the lifetime is at most a few hours.

**Verify.** Build. Then log in and decode the token (the payload is base64 JSON): `exp - iat`
should equal the new lifetime. Tokens issued before the change keep their old expiry. Rotating
`Authentication:JwtBearer:SecurityKey` is the only way to kill them early.

---

## Section 2. `token-blacklist`: sign-out revokes the token

**Why.** From Shesha **0.43.19** on the 0.43 line and **0.45.0** on main (not 0.44.x),
`TokenAuthController.SignOff` records the token's `jti` in a blacklist (`DbTokenBlacklistService`,
cached, with a cleanup job). The list is consulted only if the host's JwtBearer options call
`context.EnsureTokenIsNotBlacklistedAsync()` in `OnTokenValidated`. The framework's own
`AuthConfigurer` does this, but projects generated from older templates don't. Without it, sign-out
is cosmetic: the token keeps working until it expires. Framework history:
shesha-io/shesha-framework#1433 (PR #4517 on `releases/0.43`, ported to `main`).

**Applicability.** The check looks in the restored package
(`~/.nuget/packages/shesha.application/<SheshaVersion>/lib/*/Shesha.Application.dll`) for the
symbol `EnsureTokenIsNotBlacklistedAsync`. If the package isn't restored, it falls back to the
version rule above. (The rule comes from the published packages: 0.43.17 lacks the symbol,
0.43.19 has it, 0.43.18 is unverified. The git release tags suggest 0.43.26, which is exactly
why the assembly is checked first.) On versions without the blacklist the check reports **n/a**, and the only
control left is a short `token-lifetime`.

**Detection.** It finds every C# file with `.AddJwtBearer(...)` and passes if the file calls
`EnsureTokenIsNotBlacklistedAsync`.

**Automatic fix.** It adds `using Shesha.Authentication.JwtBearer;` and then either:
- **A:** adds `OnTokenValidated = context => context.EnsureTokenIsNotBlacklistedAsync(),` as the
  first member of an existing `new JwtBearerEvents { ... }`, or
- **B:** if there is no `Events` assignment, adds `options.Events = new JwtBearerEvents { OnTokenValidated = ... };`
  after the `TokenValidationParameters` statement, plus
  `using Microsoft.AspNetCore.Authentication.JwtBearer;`.

**Manual fix.** If `OnTokenValidated` already has a custom handler, the check won't overwrite it.
Make the blacklist check the handler's first statement:

```csharp
OnTokenValidated = async context =>
{
    await context.EnsureTokenIsNotBlacklistedAsync();
    if (context.Result?.Failure != null) return;
    // ... existing handler body ...
},
```

**Verify.** Build and start the backend, then:
1. Log in and call an authenticated endpoint (e.g. `GET /api/services/app/Session/GetCurrentLoginInfo`). Expect a user.
2. `POST /api/TokenAuth/SignOff` with the same token.
3. Repeat step 1. Expect **401**. Before the fix it returns 200.

---

## Section 3. `user-lockout`: failed-login lockout is enabled

**Why.** Without lockout, the login endpoint allows unlimited password guessing. Shesha's
framework module registers lockout **on by default** (`ISecuritySettings`: enabled, 5 attempts,
300 s; confirmed on 0.43). So in a healthy repository a source search for `LockoutEnabled` finds
**nothing**. An audit that reports "no lockout configured" from a source search alone is a false
positive. The real risks are code that turns it off or weakens it, and a changed value in the
database.

**Detection (static).**

| Pattern | Result |
|---|---|
| `UserLockOutEnabled.WithDefaultValue(false)` | FAIL (auto-fixable) |
| `UserLockOutEnabled.SetValue[Async](false)`, or a migration or seed setting `...UserLockOut.IsEnabled` to false | FAIL |
| `MaxFailedAccessAttemptsBeforeLockout` default/set above `max_attempts` (10) | WARN |
| `DefaultAccountLockoutSeconds` default/set below `min_seconds` (60) | WARN |
| `LoginAsync(..., shouldLockout: false)` | MANUAL: legitimate when re-verifying the current user's password (change-password), a bypass on a login path |

**Detection (live, optional).** With `--base-url`, `--username` and `SHESHA_ADMIN_PASSWORD`, it reads
`GET /api/services/app/AuthorizationSettings/GetSettings` and applies the same thresholds to
`isLockoutEnabled`, `maxFailedAccessAttemptsBeforeLockout` and `defaultAccountLockoutSeconds`.
This is **read-only**. The script never changes live settings.

**Automatic fix.** Only `WithDefaultValue(false)` is rewritten to `(true)`.

**Manual fix.** For live values, change them in the admin UI (Security settings), or with the
user's explicit go-ahead via `PUT /api/services/app/AuthorizationSettings/UpdateSettings`.
Send the full DTO from `GetSettings`, with only the lockout fields changed. Remove migrations that
disable lockout, or supersede them with a new migration.

Lockout applies per user as well: the setting sets `AllowedForNewUsers`, and accounts created
while it was off may carry `IsLockoutEnabled = false`. That's a candidate for a future live check.

**Verify.** Against a test account, make `max attempts + 1` wrong logins. The last should report
the account as locked. Don't do this against shared or production accounts.

---

## Section 4. `hangfire-dashboard`: the dashboard uses the framework's permission check

**Why.** The Shesha starter template maps `/hangfire` itself and passes an **app-level**
`HangfireAuthorizationFilter` whose whole rule is
`GetUsernameFromJwtToken()?.Trim().ToLower() == "admin"`. `GetUsernameFromJwtToken()` only
*parses* the `Abp.AuthToken` cookie (`JwtSecurityTokenHandler.ReadToken`). It doesn't check the
signature, expiry or blacklist. So anyone who sets the cookie to a hand-made unsigned token saying
`name: admin` gets the dashboard, where they can trigger, delete and re-queue jobs and read job
arguments. The framework's own `Shesha.Scheduler.Hangfire.HangfireAuthorizationFilter` checks
`Pages.Hangfire`, but reads the user the same way, so the same kind of forged token gets in there too.
shesha-io/shesha-framework#5554 adds `app.UseSheshaHangfireDashboard(path = "/hangfire")`
(namespace `Shesha.Scheduler.Extensions`). It validates the token, then checks `Pages.Hangfire`.

**Applicability.** The check runs on every version, because the problem exists on every version.
Only the **fix** is gated on the framework. It looks for the symbol `UseSheshaHangfireDashboard` in the
restored package (`~/.nuget/packages/shesha.scheduler/<SheshaVersion>/lib/*/Shesha.Scheduler.dll`):

| Package state | Result |
|---|---|
| Restored, has the extension | FAIL, auto-fixable |
| Restored, no extension (every release up to at least 0.45.1) | FAIL, **not applied**. The note says to upgrade Shesha and run the skill again. |
| Not restored | FAIL, **not applied**. The note says to run `dotnet restore` and run the skill again. |

There is no version-table fallback yet, because no released version ships the extension. When #5554
ships, add its first versions to `extension_available()` and update the restored-package test.

**Detection.** It finds every `.UseHangfireDashboard(...)` call and classifies it:

| Shape | Result |
|---|---|
| Template filter: an `IDashboardAuthorizationFilter` class declared in the repo that compares `GetUsernameFromJwtToken()` with `"admin"` | FAIL |
| Framework filter (`HangfireAuthorizationFilter` not declared in the repo, or qualified `Shesha.Scheduler.Hangfire.`) | FAIL |
| No `Authorization` (Hangfire default: local requests only) | WARN |
| Any other filter class, or `DashboardOptions` members other than `Authorization` (e.g. `DashboardTitle`, `AsyncAuthorization`), named arguments | MANUAL |
| Template filter class still in the repo but no longer referenced | WARN, auto-fixable (delete), whatever the version |
| No `UseHangfireDashboard` call | PASS |

**Automatic fix** (only when the extension is available):
- The call becomes `app.UseSheshaHangfireDashboard()`. The path is passed only if it isn't `/hangfire`.
- `using Shesha.Scheduler.Extensions;` is added.
- The template filter file is **deleted** if it holds only that type and nothing else references
  it after the rewrite. Its folder is removed as well if it ends up empty.
- The `using <filter namespace>;` line is removed where no remaining file declares that namespace.
  Otherwise the build would fail with CS0246. Other usings (e.g. `using Hangfire;`, still needed
  for `AddHangfire`) are left alone.

**Manual fix.** For MANUAL shapes, check whether `Pages.Hangfire` covers the custom filter's rule.
If it does, replace the call with `app.UseSheshaHangfireDashboard("<path>")` and delete the filter.
If the dashboard needs options the extension doesn't take, keep `UseHangfireDashboard` but put the
framework filter in `AsyncAuthorization` once #5554 ships. **Until the upgrade**, the only
application-level mitigation is a local filter that validates the token properly (the sketch is in #5554),
or not mapping the dashboard in production.

**Verify.** Build. If `<Project>.Web.Core.xml` is checked in, the build regenerates it without the
deleted filter's entry, so commit that too. Grant `Pages.Hangfire` to a test role. Then:
1. Open `/hangfire` without logging in. Expect **401/403**.
2. Set `Abp.AuthToken` to an unsigned token (`alg: none`, `name: admin`). Expect **401/403**. Before the fix it returns 200.
3. Log in as a user with the role. Expect the dashboard. Without the role, expect 403.

---

<!-- Next check: "## Section 5. `<check-id>`: <title>". See adding-a-check.md. -->
