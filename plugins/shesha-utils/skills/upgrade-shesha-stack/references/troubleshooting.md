# Troubleshooting

- [Restore cannot authenticate to the private feed](#restore-cannot-authenticate-to-the-private-feed)
- [NU1605 package downgrade errors](#nu1605-package-downgrade-errors)
- [npm install returns 401](#npm-install-returns-401)
- [A property resolves to compat instead of exact](#a-property-resolves-to-compat-instead-of-exact)
- [A package version exists on NuGet but not npm](#a-package-version-exists-on-nuget-but-not-npm)

## Restore cannot authenticate to the private feed

**Symptom:** `Unable to load the service index for source
https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/...`, or a
401, or packages resolving only from nuget.org.

**Two independent causes, usually together.**

*The config is not found.* Many Shesha projects keep `NuGet.Config` at
`backend/.nuget/NuGet.Config`. That is the NuGet 2.x solution-level convention.
`dotnet` walks parent *directories* looking for `nuget.config`; it does not look
inside a `.nuget` subfolder. Visual Studio still honours it, which is why the
build works in the IDE and fails on the command line. Pass it explicitly:

```bash
dotnet restore <solution>.sln --configfile backend/.nuget/NuGet.Config
```

*The config has no credentials.* The checked-in file lists sources only —
credentials are expected from a credential provider. If
`~/.nuget/plugins/netcore` does not exist, no provider is installed and there is
nothing to supply them.

The reliable fix without installing anything is a temporary config that injects
the PAT. Write it **outside the repository** so the token is never committed:

```python
import os
pat = os.environ["SHESHA_FEED_PAT"]
open(cfg_path, "w").write(f'''<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" protocolVersion="3" />
    <add key="nuget.shesha.dev" value="https://pkgs.dev.azure.com/boxfusion/_packaging/nuget.shesha.dev/nuget/v3/index.json" />
  </packageSources>
  <packageSourceCredentials>
    <nuget.shesha.dev>
      <add key="Username" value="pat" />
      <add key="ClearTextPassword" value="{pat}" />
    </nuget.shesha.dev>
  </packageSourceCredentials>
</configuration>
''')
```

Copy any other sources (such as DevExpress, whose URL embeds its own key) from
the project's own config. Then `dotnet restore --configfile <that file>`. Never
echo the PAT into terminal output.

## NU1605 package downgrade errors

**Symptom:** the build fails with `error NU1605: Warning As Error: Detected
package downgrade: Shesha.Framework from 0.0.1 to 0.0.0-build74768` even though
restore succeeded and every version in `Directory.Build.props` is correct.

**Check first:** is the dependency graph in the error rooted at a project that
is *not* in the `.sln`? The error lines look like:

```
error NU1605:  <Some Project> -> Shesha.Core 0.0.1 -> Shesha.Framework (>= 0.0.1)
```

If `<Some Project>` is not a solution member, this is **stale build state, not a
real version conflict.**

**Cause.** Two `.csproj` files in the same directory share one `obj/`. NuGet's
per-project files are name-prefixed and coexist safely, but `project.assets.json`
has a single fixed filename, so whichever project restored last owns it. A
stray or backup `.csproj` — even one absent from the solution — leaves its own
dependency graph behind, and the real project then builds against it.

Confirm in one step:

```python
import json
d = json.load(open("<that-dir>/obj/project.assets.json"))
print(d["project"]["restore"]["projectName"])
```

If that name is not the project you expect, you have found it.

**Recovery.** Restore and build the real project explicitly, which rewrites the
assets file, then rebuild the solution:

```bash
dotnet build <path-to-real>.csproj --configfile <config>
dotnet build <solution>.sln --no-restore -v m
```

Sln-scoping the restore is correct and necessary, but it does **not** prevent
this on its own — the poisoned assets file is already on disk from an earlier
out-of-band restore. Report the cause rather than the raw error, and note that
it recurs whenever anything restores the stray project again. Do not delete a
stray `.csproj` without asking.

## npm install returns 401

Two files must both be right:

1. The frontend root's `.npmrc` maps the scope to the private registry:
   `@shesha-io:registry=https://pkgs.dev.azure.com/boxfusion/_packaging/npm.shesha.dev/npm/registry/`
2. The user-level `~/.npmrc` holds credentials for that registry path
   (`:username`, `:_password` base64, `:email` — the Azure Artifacts form).

The project file is committed and the credentials are not, so a fresh machine
has the first and lacks the second. Never write credentials into the project
`.npmrc`. When redacting these files for output, mask `_password`/`_authToken`.

## A property resolves to compat instead of exact

No build of that module group declares the target Shesha version, so the newest
build with a *lower* floor was chosen. NuGet will resolve it happily — floors
are minimums — but the module's assemblies were compiled against an older
Shesha, so the risk is binary incompatibility at runtime, not restore failure.

Surface it to the user, proceed, and rely on the build plus runtime testing.
If the module was recently rebuilt, re-running resolution later may find an
exact match.

## A package version exists on NuGet but not npm

The frontend and backend halves of a module are published by separate pipeline
steps, so one can lag. The resolver flags this as `NOT ON NPM FEED`.

Do not substitute a different npm version to make it install — that breaks the
mirror invariant. Report it and let the user decide whether to wait for the
publish or pick a different target Shesha version.
