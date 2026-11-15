# Starting and Stopping the Dev Servers

The live half of this audit needs the backend running. This file is the whole procedure —
it replaces the former `starting-dev-servers` and `stopping-dev-servers` skills.

## Contents
- Step 1: Detect the layout
- Step 2: Preconditions
- Step 3: Start the backend
- Step 4: Wait for the backend correctly
- Step 5: Start the frontend
- Step 6: Verify
- Stopping
- Note on interrupted startup

Defaults: backend port `21021`, frontend port `3000`.

## Step 1: Detect the layout

Do not assume this repository's paths. Detect them:

**Backend Web.Host project** — the `.csproj` whose `Sdk` is `Microsoft.NET.Sdk.Web` and whose
directory contains `appsettings.json` plus a `Startup/` or `Program.cs`. Typically
`backend/src/*.Web.Host/*.Web.Host.csproj`.

```bash
find . -name "*.Web.Host.csproj" -not -path "*/obj/*" -not -path "*/bin/*"
```

**Frontend directory** — a directory with `next.config.js` and a `package.json` depending on
`@shesha-io/reactjs`. Usually `adminportal/`, sometimes also `publicportal/`.

**Backend URL** — read `App:ServerRootAddress` from the Web.Host `appsettings.json`; fall back to
`http://localhost:21021`. Read `App:CorsOrigins` to confirm the frontend port is allowed.

Report what was detected before starting anything.

## Step 2: Preconditions

1. **Database reachable.** Read `ConnectionStrings:Default` from `appsettings.json`. If the database
   does not exist, stop and tell the user — do not create it silently. Many Shesha repos ship a
   `.bacpac` or `.backup` at the repo root for this purpose; point the user at it if present.
2. **Dependencies restored.** If the frontend has no `node_modules`, run `npm install` in the
   frontend directory first. If it fails with HTTP 401, the Azure DevOps token in the user's
   `~/.npmrc` has expired — say so rather than retrying.
3. **Backend built.** Run `dotnet build <solution> --no-restore`. If restore is needed and the
   private Shesha feed is not configured, pass the repo's NuGet config explicitly, e.g.
   `dotnet restore <solution> --configfile backend/.nuget/NuGet.Config`.

## Step 3: Start the backend

Run in the background, from the repository root:

```bash
ASPNETCORE_ENVIRONMENT=Development ASPNETCORE_URLS=http://localhost:21021 \
  dotnet run --no-build --no-restore --no-launch-profile --project <WebHost.csproj>
```

Two flags matter:
- `--no-launch-profile` — Shesha templates ship a `launchSettings.json` with only `IIS Express` and
  `Docker` profiles. Without this flag `dotnet run` aborts with "A usable launch profile could not
  be located."
- `ASPNETCORE_URLS` — there is no Project profile to supply the port, so without this the backend
  binds to the ASP.NET default (5000/5001) and the frontend cannot reach it.

## Step 4: Wait for the backend correctly

**The backend does not bind its port until migrations and bootstrappers finish.** On a fresh or
newly-restored database this takes 10–20 minutes: several hundred FluentMigrator migrations, then
the Shesha bootstrappers (permissioned objects, entity configs, settings, reference lists). On a
warm database it is well under a minute. Never conclude the backend has failed because the port is
not open yet, and say so before waiting rather than appearing to hang.

Wait on a condition, not a fixed sleep:

```bash
until curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
  http://localhost:21021/swagger/index.html 2>/dev/null | grep -qv '^000$'; do sleep 10; done
```

Also break out on `Application startup exception`, `Unhandled exception` or `HostAbortedException`
in the console output, so a real crash is not mistaken for slow startup.

For progress during the wait, read the log4net file — the console is nearly silent during
bootstrapping while this file is not:

```
<WebHost>/bin/Debug/net8.0/App_Data/Logs/App_<MACHINE>.log
```

Lines such as `Run bootstrapper: EntityConfigsBootstrapper...` and
`Bootstrap assembly <name> - finished` show real progress.

**Startup errors that are expected and benign** — do not report these as failures:
- `Invalid object name 'frwk_application_startups'` — logged before the migration that creates the
  table.
- `filter-def for filter named 'MustHaveTenant' was never used` — an NHibernate configuration
  notice.

## Step 5: Start the frontend

The frontend is only needed for the coded-frontend scan if you intend to exercise screens by hand;
the catalogue phase reads frontend **source**, not a running server. Start it when the user asks,
or when a finding needs confirming in the UI.

```bash
cd <frontend-dir> && npm run dev
```

Wait for `Ready in` in the output. The first page request compiles on demand and can take 20–60
seconds; a slow first response is not a failure.

## Step 6: Verify

| Check | Expected |
|-------|----------|
| `GET <backend>/swagger/index.html` | 200 (or 403 if `SwaggerUiEnabled` is false — still healthy) |
| `POST <backend>/api/TokenAuth/Authenticate` with the app's admin credentials | 200 with an `accessToken` |
| `GET http://localhost:3000` | 200 |

Report both URLs, the detected paths, and whether the backend ran migrations on this start. Note
that servers started from this session stop when it ends.

## Stopping

**Identify the listeners first** — another project may own the port:

```bash
netstat -ano | grep -E ':(3000|21021)\b' | grep LISTENING
```

Resolve each PID to a process name and report it. If a PID is not `dotnet`, `node` or `next`, ask
the user before terminating it.

If this session started the servers as background tasks, prefer stopping those tasks directly —
that terminates the process tree cleanly. Otherwise kill by port:

```bash
netstat -ano | grep ":21021" | grep "LISTENING" | awk '{print $5}' | sort -u \
  | xargs -r -I{} taskkill //F //PID {}

netstat -ano | grep ":3000" | grep "LISTENING" | awk '{print $5}' | sort -u \
  | xargs -r -I{} taskkill //F //PID {}
```

`npm run dev` spawns a child `next` process. Killing the parent alone can leave the port held —
always re-check and repeat if a listener remains:

```bash
netstat -ano | grep -E ':(3000|21021)\b' | grep LISTENING || echo "both ports free"
```

Report which servers were stopped, which were already stopped, and any port still held together
with the process holding it.

## Note on interrupted startup

If the backend is stopped mid-migration it leaves the database partially migrated. This is safe —
FluentMigrator records each migration transactionally and resumes on the next start — but that next
start will again take a long time. Say so when stopping a backend that had not yet finished
starting.
