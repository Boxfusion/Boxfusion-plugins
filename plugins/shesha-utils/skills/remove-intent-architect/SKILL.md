---
name: remove-intent-architect
description: Removes all Intent Architect artifacts and references from a Shesha (or any .NET) project. Deletes the root-level intent/ metadata folder and .isln solution files, removes Intent.* NuGet package references, and strips Intent-related using statements, [IntentManaged(...)] attributes, and [assembly: IntentTemplate(...)] / [assembly: DefaultIntentManaged(...)] statements. Use when the user asks to remove, drop, clean up, or decouple from Intent Architect, the intent folder, or Intent.RoslynWeaver / Intent.VisualStudio dependencies.
---

# Remove Intent Architect

Intent Architect is a code-generation tool that leaves behind a metadata folder plus package references, attributes, and using-statements sprinkled through the C# source. This skill removes all of it so the project no longer depends on it.

## What to remove

1. The root-level `intent/` folder (contains `.config`/`.xml` metadata and often the `.isln` file).
2. Any `*.isln` (Intent solution) files anywhere in the repo.
3. `Intent.*` NuGet `PackageReference` entries in `.csproj` files (commonly `Intent.RoslynWeaver.Attributes`, `Intent.VisualStudio.Projects`).
4. `using Intent.RoslynWeaver.Attributes;` statements.
5. `[assembly: IntentTemplate(...)]` statements.
6. `[assembly: DefaultIntentManaged(...)]` statements.
7. `[IntentManaged(...)]` attributes (on classes, methods, properties — often on their own line).

## Procedure

### Step 1: Survey the scope

From the repo root, find everything that references Intent so you know what the script must clean and what to verify afterward:

```bash
ls -d intent 2>/dev/null                       # root metadata folder
find . -name "*.isln"                           # Intent solution files
grep -rn "Intent" --include="*.cs" --include="*.csproj" .
```

### Step 2: Run the removal script

Run the bundled script from the repo root (pass the root as the argument):

```bash
python "$CLAUDE_PLUGIN_ROOT/skills/remove-intent-architect/scripts/remove_intent.py" .
```

The script deletes the `intent/` folder and `.isln` files, strips `Intent.*` package references from `.csproj` files, and removes the Intent using-statements, assembly attributes, and standalone `[IntentManaged(...)]` attribute lines from `.cs` files. It prints every change it makes and lists any remaining `Intent` matches for manual review.

If Python is unavailable, perform the edits manually using the survey output from Step 1 — the removals are line-based and mechanical.

### Step 3: Handle leftovers manually

The script only removes `[IntentManaged(...)]` attributes that sit on their own line. If Step 2's report shows remaining matches (e.g. an inline `[IntentManaged(Mode.Ignore)] public ...` on the same line as code, or a multi-line attribute), edit those by hand — remove only the attribute, keeping the member it decorates.

Note: an `[IntentManaged(Mode.Ignore)]` attribute is sometimes placed *before* a `/// <summary>` doc comment. Removing the attribute line is correct; leave the doc comment.

### Step 4: Verify

Confirm nothing remains, then build:

```bash
grep -rn "Intent" --include="*.cs" --include="*.csproj" .   # expect no matches
dotnet build <solution>.sln
```

The build must succeed with 0 errors before considering the task complete.
