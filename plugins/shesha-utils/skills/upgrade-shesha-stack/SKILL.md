---
name: upgrade-shesha-stack
description: Upgrades a Shesha project to a target Shesha version, resolving the matching version of every other Shesha and Boxfusion module from the private Azure Artifacts feed, updating the backend Directory.Build.props and all frontend @shesha-io/* packages, then restoring, building and installing to verify. Use when the user wants to upgrade, update, bump or migrate Shesha, BoxStack or Shesha module versions, or asks which module versions are compatible with a given Shesha version.
---

# Upgrade Shesha Stack

Take ONE input from the user — the target Shesha version (e.g. `0.43.37`) — and
derive everything else. Do not ask the user for module versions; resolve them
from the feed.

The user may instead name a BoxStack release number. There is no reliable
offline mapping for those, so ask them which Shesha version that release
contains rather than guessing.

## Prerequisite: feed credentials

Resolution requires `SHESHA_FEED_PAT` — an Azure DevOps PAT with **Packaging:
Read** on the `boxfusion` organisation, set in the `env` block of
`~/.claude/settings.json`. Edits to that file are picked up without restarting
the session.

If it is unset or still a placeholder, stop and ask for it. **Never fall back to
nuget.org or npmjs.org.** Several of these package names also exist publicly
under a completely different version series (`Shesha.Sms.*` is the clearest
case), so a public-feed fallback returns confidently wrong versions instead of
failing.

## Workflow

### 1. Check preconditions

Run `git status`. Report any pre-existing uncommitted changes so the user can
tell them apart from this upgrade's edits. Do not commit or stash unless asked.

### 2. Resolve the version set

```bash
python scripts/resolve_versions.py --repo <repo-root> --target <shesha-version> --json plan.json
```

The script discovers the project's own shape and prints a plan. It:

- reads every property from `backend/Directory.Build.props`
- finds which packages each property versions, from the `.csproj` files **named
  in the `.sln`**
- picks, for each property, the newest version published by *every* package in
  that group whose `.nuspec` shows it was built against the target Shesha
  version (`exact`), falling back to the newest with a lower floor (`compat`)
- finds every `@shesha-io/*` dependency in every `package.json` in the repo and
  mirrors its backend module's version, resolving frontend-only packages
  against the npm feed instead
- verifies each frontend version actually exists on the npm feed

Exit code is non-zero when something is unresolved. Read the notes it prints: a
`compat` result means no build was compiled against the target, and needs
confirming at build time.

### 3. Review the plan with the user

Show the resolved table before editing anything. Call out explicitly:

- any property resolved as `compat` rather than `exact`
- any `UNRESOLVED` row
- any hardcoded version the script reported in a `.sln` project — those bypass
  the property and will not move

### 4. Apply the backend changes

Edit **only** the property values in `backend/Directory.Build.props`. Never edit
versions in individual `.csproj` files; they reference `$(...)` and are already
correct.

### 5. Apply the frontend changes

For every row in the plan's `frontend` list, write the version in that exact
file and section, using the `write` value from the plan.

- **Always write a caret range (`"^0.43.37"`)**, even where the project
  currently pins exactly. This lets patch releases flow in without another
  upgrade pass. The `write` field in the plan is already in caret form.
- The `overrides` block needs updating too. It is the most commonly missed
  spot, and a stale pin there silently forces an old transitive copy.
- Never touch a `package.json`'s own `name`/`version`, and never bump a
  workspace package that a sibling workspace package depends on. Release
  versioning belongs to the build pipeline.

### 6. Verify the backend

Restore and build the **solution**, never a directory or an individual project:

```bash
cd backend
dotnet restore <solution>.sln
dotnet build <solution>.sln --no-restore -v m
```

Two things routinely go wrong here — see
[references/troubleshooting.md](references/troubleshooting.md) for both:

- **Restore cannot authenticate.** A `NuGet.Config` under `backend/.nuget/` is
  the old NuGet 2.x convention, is *not* auto-discovered by `dotnet`, and
  usually carries no credentials.
- **`NU1605` package downgrade errors.** If the error's dependency graph is
  rooted at a project that is *not* in the solution, this is stale build state
  rather than a real conflict — recover and retry.

Report the build result honestly. If it fails, establish whether the upgrade
caused it before saying so: build the individual failing project, and check
whether the failure names any package the upgrade touched.

### 7. Verify the frontend

```bash
cd adminportal        # and each other frontend root in the plan
npm install --no-fund --no-audit
```

Editing `package.json` alone changes nothing about what installs — the lockfile
must be regenerated. Afterwards **confirm** it took:

```bash
grep -c "<old-version>" package-lock.json          # expect 0
node -p "require('./node_modules/@shesha-io/reactjs/package.json').version"
```

Checking the installed version matters more with caret ranges than with exact
pins: a range can resolve to something newer than the resolved target. For a
`0.x` module `^0.43.37` stays within `0.43.x`, but for a `1.0.0`-and-above
module `^2.6.26` admits any `2.x` — including a future build compiled against a
newer Shesha line. The committed lockfile is what actually holds the version
steady for CI and other developers, so commit it alongside the manifests, and
report the installed version rather than assuming it equals the target.

`npm install` needs the `@shesha-io` scope pointed at the private registry (in
the frontend root's `.npmrc`) plus credentials for that registry in the
user-level `~/.npmrc`. Missing either produces a confusing 401.

### 8. Report

State before/after for every property and package, the build result, the
lockfile confirmation, and anything left unresolved or flagged `compat`.

## Rules

- **One input.** The target Shesha version. Everything else is derived.
- **Private feed only.** Never resolve these packages from public registries.
- **`Directory.Build.props` only** on the backend. Never edit `.csproj` versions.
- **Frontend mirrors backend.** An `@shesha-io/*` package takes the same version
  as its backend module. This holds for proper release versions; it does not
  hold for CI build-number versions (`0.0.0-build70972`, `0.0.64973-build`),
  which must be raised with the user rather than guessed.
- **Not a 1:1 mapping.** Some backend modules have no frontend package, and some
  frontend packages have no backend module. Neither is an error.
- **Never "just take latest".** Every module has newer major versions built
  against a *newer* Shesha line, and prereleases can outsort releases. Latest
  reliably produces a broken tree.
- **NuGet dependency versions are floors, not pins.** A `.nuspec` saying
  `version="0.43.34"` means `>= 0.43.34`, so it records what a module was built
  *against*. A mismatch risks binary incompatibility, not a resolution failure.
- **The `.sln` defines the project.** Ignore `.csproj` files it does not name.
- **Version fields belong to the pipeline.** Never increment a project's own
  version.

## Notes on the module ecosystem

Properties seen in real projects, each versioning a group of packages:
`SheshaVersion` (the Shesha core line — `Shesha.Framework`, `.Core`,
`.Application`, `.NHibernate`, `.FluentMigrator`, `.Import`,
`.Web.FormsDesigner`), `SheshaEnterpriseVersion` (`Shesha.Enterprise.*`,
`Shesha.Workflow`, `Shesha.FacialRecognition.*`, `Shesha.Sms.*`),
`DevExpressVersion`, `ShiftManagementVersion`, `DepVersion`,
`SheshaMobileVersion`, and `ContentManagementVerison` — note that misspelling is
real and load-bearing, so never assume property names end in `Version`.

The npm counterpart of the Shesha core line is `@shesha-io/reactjs`, a name that
derives from no NuGet id. Other modules map by slug: `Shesha.Enterprise.Domain`
→ `@shesha-io/enterprise`, `boxfusion.devexpressreporting.Application` →
`@shesha-io/devexpressreporting`.

A frontend root is not always called `adminportal` — projects also ship
`publicportal`, sometimes several, each an npm workspace with its own
`packages/*`. These folders are frequently gitignored, so a gitignore-aware
file search finds nothing; walk the filesystem instead.
