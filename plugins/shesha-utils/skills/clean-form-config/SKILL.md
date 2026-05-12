---
name: clean-form-config
description: Analyzes a Shesha form configuration JSON and removes dead/obsolete component properties, strips console.log calls from JS code strings, validates property value types, validates the shape of dropdown values items, detects scripts referencing component labels instead of propertyNames, runs layout validations (container dimension overflow, labelCol+wrapperCol span checks, device-specific style path conflicts), validates JavaScript syntax of embedded code strings, auto-fixes API calls missing try-catch by wrapping the function body in try/catch, and auto-fixes API calls in async-context properties that are missing async/await by adding the async keyword and awaiting calls. Falls back to manual review when function structure is ambiguous. Also detects API calls using .then() chaining and flags them for conversion to async/await + try-catch. Use when a form has been migrated, components have been refactored, or you want to clean up stale properties and debug statements.
---

# Clean Form Configuration

Identify and remove **dead properties**, **console.log debug statements**, and **type mismatches** from a Shesha form configuration.

---

## Step 1: Load the component properties index

Read the bundled index from the skill's own assets folder:

```
plugins/shesha-developer/skills/clean-form-config/assets/component-properties.json
```

This file is maintained by the skill author and ships with the plugin — no generation step is needed. Proceed directly to Step 2.

> **Note for skill maintainers:** To refresh the index after a shesha-reactjs upgrade, follow [generate-index.md](generate-index.md) and replace the file above.

---

## Step 2: Load the form config

Choose one of:

**Option A — Fetch from API**: Follow [api.md](api.md) to resolve the base URL, authenticate, and retrieve the form by module + name.

**Option B — Local file**: Ask the user for the file path, then use `Read` to load it.

In both cases normalise to `{ components, formSettings }` as described in the Normalisation section of [analysis.md](analysis.md) before continuing.

---

## Step 3–8: Analyse and clean

Follow [analysis.md](analysis.md) for:

- **Step 3** — Load and interpret the component properties index (v2 format).
- **Step 4** — Walk the component tree; identify dead properties and unknown types.
- **Step 4b** — Scan all string values for `console.log` calls.
- **Step 4c / 4d / 4e / 4f** — Type-check valid properties; validate dropdown `values` item shapes; run layout checks (overflow, span, device-style path); scan scripts for label used instead of propertyName.
- **Step 4g** — Validate JavaScript syntax of all embedded code strings; flag broken scripts as `[CRITICAL]`.
- **Step 4h** — Detect API calls missing try-catch; auto-fix by wrapping the function body in try/catch where the structure is unambiguous; fall back to `[MANUAL REVIEW]` for complex scripts.
- **Step 4i** — Detect API calls in async-context properties (onFinish, onSubmit, getData, etc.) missing async/await; auto-fix by adding `async` to the function signature and `await` before the call; fall back to `[MANUAL REVIEW]` for ambiguous structures. Also detects `await` used outside an `async` function (Scenario A) and auto-fixes it.
- **Step 4j** — Detect API calls using `.then()` chaining; flag as `[MANUAL REVIEW]` with a recommendation to convert to async/await + try-catch.
- **Step 5 / 5b / 5c / 5d / 5e / 5f / 5g / 5h / 5i / 5j** — Present findings (dead props, console.log, type mismatches, values shape issues, layout issues, label references, script syntax errors, missing try-catch, missing async/promise, .then() chaining).
- **Step 6** — Single confirmation prompt.
- **Step 7** — Apply all cleanups and output cleaned JSON.
- **Step 8** — Summary with size reduction.

Layout checks are defined in [layout-checks.md](layout-checks.md) — new checks can be appended there as L3, L4, etc.

---

## Step 9: Push cleaned config back to the API (optional)

After producing the cleaned JSON, ask the user:

> The form has been cleaned. Would you like to push the updated config back to the Shesha backend via the API? (yes / no)

**If no** → skip this step, work is done.

**If yes** → follow Section 5 of [api.md](api.md) to call `ImportJson`.

- If the form was loaded via the API (Step 2 Option A), `FORM_ID` and `ACCESS_TOKEN` are already available — use them directly.
- If the form was loaded from a local file (Step 2 Option B), or `FORM_ID` / `ACCESS_TOKEN` are not available, first follow [api.md](api.md) sections 1–2 to resolve the base URL and authenticate, then ask the user:
  > Please enter the form's `itemId` (the UUID of the form configuration record):

---

## Notes

- **Conservative approach**: ambiguous properties go to manual review, not auto-clean.
- **Structural keys are never removed**: `id`, `type`, `parentId`, `components`.
- **Nested objects are not deep-cleaned**: only top-level component keys are checked.
- **`IPropertySetting` wrappers** (`{ _mode, _value, _code }`) are valid for any property.
- **`_mode: 'code'` values are never type-checked** — runtime expressions.
- **`null` values are never type-checked** — valid for any property type.
- To regenerate the index after upgrading shesha-reactjs, delete `.claude/shesha/component-properties.json` and re-run the skill.
