---
name: remove-intent-architect
description: Scrubs all Intent Architect artifacts and references from a Shesha (or any .NET) project. Deletes the intent/ metadata folder, Intent.Modules/ folder and .isln files, removes Intent.* NuGet package references, strips Intent using-statements, [IntentManaged(...)] attributes and [assembly: IntentTemplate/DefaultIntentManaged(...)] statements, regenerates packages.lock.json files, and removes Intent CLI steps, variables and credential groups from Azure DevOps pipelines. Use when the user asks to remove, scrub, strip, clean up, or decouple from Intent Architect, the intent folder, the Intent CLI, or Intent.RoslynWeaver dependencies.
---

# Remove Intent Architect

Intent Architect is a code generator that leaves a metadata folder, package references, attributes and using-statements in C# source, and Intent CLI steps in CI pipelines. This skill removes all of it so the project no longer depends on Intent.

## Procedure

### Step 1: Branch and dry run

Work on a dedicated branch (e.g. `chore/remove-intent-architect`) so the change is one reviewable diff. From the repo root:

```bash
python "$CLAUDE_PLUGIN_ROOT/skills/remove-intent-architect/scripts/remove_intent.py" . --dry-run
```

The dry run lists every planned change, then the leftovers the script will not handle (see Step 2 output sections).

### Step 2: Run the script

```bash
python "$CLAUDE_PLUGIN_ROOT/skills/remove-intent-architect/scripts/remove_intent.py" .
```

It removes:

- root `intent/` and `Intent.Modules/` folders, any nested `intent/` folder holding an `.isln` (e.g. `backend/intent/`), and any other `*.isln` files
- `Intent.*` `<PackageReference>` / `<PackageVersion>` entries (single- or multi-line) in `.csproj`, `.props`, `.targets`
- `using Intent.*;`, `[assembly: IntentTemplate(...)]`, `[assembly: DefaultIntentManaged(...)]` and standalone `[IntentManaged(...)]` lines, including commented-out (`//`) versions
- in Azure DevOps `.yml`/`.yaml`: Intent CLI steps (live or commented out, e.g. `install intent cli`, `run intent cli`), the `intentSolutionPath` variable and the `Intent Architect Credentials` variable group. Only the innermost list item mentioning Intent is removed, never its parent stage or job

It preserves each file's BOM and line endings byte-for-byte (repos often mix LF and CRLF) and collapses blank lines orphaned by a removal, so the diff is deletions only.

It then reports four sections:

| Section | Action |
|---|---|
| Remaining Intent references in code | Fix by hand (Step 3) |
| packages.lock.json with a direct Intent pin | Regenerate (Step 4) |
| packages.lock.json with Intent only as a transitive dependency | Leave. Upstream packages (e.g. `Shesha.Enterprise.*`) were themselves built with Intent and depend on `Intent.RoslynWeaver.Attributes`; this is outside the project's control |
| Intent references in pipelines / scripts / docs / config | Clean up (Step 5) |

### Step 3: Fix code leftovers

Typical leftovers are inline attributes on the same line as code (`[IntentManaged(Mode.Ignore)] public ...`) or combined attribute lists (`[HttpGet, IntentManaged(...)]`). Remove only the Intent attribute and keep the member. An `[IntentManaged(...)]` line placed before a `/// <summary>` block is removed by the script; the doc comment stays.

The report matches precise Intent markers only, so names like `IntentResult` or a bot-framework `chooseIntentTemplatePrefix` are not flagged and must not be touched.

### Step 4: Restore and build

With `RestorePackagesWithLockFile` enabled, `packages.lock.json` still pins the removed package until restore regenerates it:

```bash
dotnet restore <solution>.sln
dotnet build <solution>.sln --no-restore
```

If a pipeline restores with `--locked-mode`, the regenerated lock files must be committed in the same change or CI fails. The build must finish with 0 errors.

If restore fails with `NU1101` (package not found) or `401` against the private feed, the config is under `backend/.nuget/NuGet.Config`, which `dotnet` does not auto-discover, and it carries no credentials. Pass a temporary config written **outside the repo** that copies its sources and adds `SHESHA_FEED_PAT` credentials. See the upgrade-shesha-stack skill's `references/troubleshooting.md` ("Restore cannot authenticate"). A restore that succeeds without it may only be using the local package cache.

### Step 5: Review pipelines, scripts and docs

Review the pipeline diff: the script removes whole Intent steps, and a live `install intent cli` step means the change affects CI. Then edit what the last report section still lists by hand, e.g. README/CLAUDE.md/docs lines describing the `intent/` folder, or a `.ps1` running `intent-packager`. Delete whole steps at their list indentation so the YAML stays valid. Mention in the summary that the `Intent Architect Credentials` variable group in Azure DevOps can be deleted once no pipeline references it; that is a server-side change outside the repo.

### Step 6: Verify

Re-run the script with `--dry-run`. It must report nothing removed, no code leftovers, no direct lock pins, and no pipeline/doc references; only transitive lock entries may remain. Review `git diff --stat`: apart from regenerated lock files, the change should be deletions.
