# Troubleshooting

- [Restore cannot authenticate to the private feed](#restore-cannot-authenticate-to-the-private-feed)
- [NU1605 package downgrade errors](#nu1605-package-downgrade-errors)
- [npm install returns 401](#npm-install-returns-401)
- [A property resolves to compat instead of exact](#a-property-resolves-to-compat-instead-of-exact)
- [A package version exists on NuGet but not npm](#a-package-version-exists-on-nuget-but-not-npm)
- [NU1605 from a hardcoded third-party pin](#nu1605-from-a-hardcoded-third-party-pin)
- [Build errors after a large module jump](#build-errors-after-a-large-module-jump)
- [npm install fails with ERR_INVALID_ARG_TYPE](#npm-install-fails-with-err_invalid_arg_type)
- [The committed lockfile does not match package.json](#the-committed-lockfile-does-not-match-packagejson)
- [The build modifies tracked XML doc files](#the-build-modifies-tracked-xml-doc-files)

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

## NU1605 from a hardcoded third-party pin

**Symptom:** restore fails with `NU1605 ... Detected package downgrade:
SkiaSharp.NativeAssets.Linux from 3.119.0 to 3.116.1`, rooted at a project that
*is* in the solution.

**Cause.** A module moved a third-party dependency forward (DevExpressReporting
2.6.27 requires `SkiaSharp.NativeAssets.Linux >= 3.119.0`), but a project pins
that package directly with a hardcoded `Version`. These pins usually exist only
to match the module, so they must follow it.

**Fix.** Read the module's `.nuspec` for the version it now requires and bump
the hardcoded pins to that version. This is the one case where editing a
`.csproj` version is correct: the pin is not managed by any property. Grep every
project for the package id, not only the one named first in the error.

## Build errors after a large module jump

Moving a module across several releases (or off a CI build onto a release)
can surface API changes, typically:

- **a renamed entity** -- e.g. Dep's `Contact` became `DirectoryContact`, so
  `ShaSpecification<Contact>` no longer compiles
- **a changed base-class constructor** -- e.g. ServiceManagement's
  `CaseViewPermissionExpressionBuilder` gained an
  `IRepository<OrganisationPerson, Guid>` parameter

The module's source is usually in another local repo. Find the change there
(`git log -S "<OldName>"`, or read the current class), confirm the replacement
has the same shape, and make the minimal fix in the consuming project. For a
constructor change, add the parameter and pass it through; check nothing news
the class up by hand. For an entity rename, check the module shipped a
migration that renames the table and discriminator, and that the consuming
project has no other code or configuration referencing the old name. Report
every such fix in the PR description.

## npm install fails with ERR_INVALID_ARG_TYPE

**Symptom:** `npm error The "from" argument must be of type string. Received
undefined`, with `rollbackMoveBackRetiredUnchanged` in the stack trace of the
debug log. Dependency resolution in the log looks correct.

**Cause.** An earlier file operation during reify failed and npm crashed while
rolling it back, hiding the original error. It reproduces on every retry when
the existing `node_modules` cannot be reconciled.

**Fix.** Do a clean install -- but with care, because npm workspace packages are
linked into `node_modules` as junctions/symlinks pointing at real source:

1. List links first: `find node_modules -maxdepth 2 -type l` (or
   `dir /AL /S /B node_modules`).
2. Remove each link on its own with `rmdir` (removes the link, not its target)
   and confirm the workspace source is intact.
3. Only then delete `node_modules` and run `npm install`. Keep `package-lock.json`.

Get the user's confirmation before deleting `node_modules`.

## The committed lockfile does not match package.json

Common after earlier upgrades that edited `package.json` without re-running
`npm install`: the manifest says `5.1.7` while `package-lock.json` still pins
`5.1.2`, so `npm ci` in the pipeline installs the old version. The regenerated
lockfile fixes it. Say so in the PR, because the diff will show larger version
jumps than the manifest change suggests.

Large lockfile shrinks are usually explainable -- compare package entries
before and after rather than reading the line diff. Seen so far: a nested
duplicate of `@shesha-io/reactjs` in a workspace collapsing into the root copy,
and a module dropping a heavy dependency (chat-service leaving
`botframework-webchat`).

## The build modifies tracked XML doc files

Some projects commit their generated `<DocumentationFile>` output (e.g.
`Web.Core.xml`). Building regenerates it with docs for code that was already
there. That change is unrelated to the upgrade -- revert it before committing
(`git checkout -- <file>.xml`) so the PR stays focused.
