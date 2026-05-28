---
name: create-test-from-devops
description: Imports Azure DevOps Test Plan / Test Suite test cases via the Azure DevOps MCP server (@azure-devops/mcp) and generates paired markdown test plans + recorded Playwright specs under test-plans/. Trigger phrases include "create test from devops", "import test plan from azure devops", "generate tests from test plan <id>", "pull test cases from devops", "create tests from ADO suite". The user provides an Azure DevOps Test Plan ID (and optionally a Suite ID to narrow it). The skill connects via the MCP, lists the suites and test cases, fetches each test case work item's Microsoft.VSTS.TCM.Steps field, converts the action/expected-result pairs into the prefixed TC-NN plan format per test-plans/RULES.md (one .md plan per suite, one TC per ADO test case), then records real selectors live via Playwright MCP into a paired .spec.ts using the same recording loop as the create-test skill. Reads App URL, environment, credentials, and the Azure DevOps org/project from CLAUDE.md. This skill authors only — the plans are executed later by the run-test skill, it does NOT run them.
---

# Create Test From DevOps

Import test cases from an Azure DevOps Test Plan and author a markdown plan **and** its paired Playwright spec with **real selectors recorded live**. This skill authors only — it does NOT run the tests (that's `/RunTest`).

It is the `create-test` skill with the source flipped: instead of the user typing high-level steps, the steps come from Azure DevOps test case work items. Everything downstream — the `.md` plan format, the live MCP recording loop, the `.spec.ts` shape — is identical to `create-test`.

## Input format

Ask the user once, using exactly this format, then stop asking:

```
Test Plan ID: <Azure DevOps test plan id, e.g. 1042>
Suite ID:     <optional — leave blank to import every suite in the plan>
Folder:       <optional — leave blank to auto-pick from the suite name>
```

**If their first message already supplies a plan id (and optional suite id), skip the prompt and proceed.**

Never ask for App URL, credentials, environment, today's date, or file path — those come from `CLAUDE.md`.

## Pre-flight (mandatory, in order)

1. Read `CLAUDE.md` → App URL, Environment, Credentials, today's date, **and the `## Azure DevOps` section** (Organization + Project).
2. Read `test-plans/RULES.md` → prefixes, snapshot rule, assertion rules, hybrid execution model (§8).
3. Read the closest neighbour plan in the target folder. Match its style, depth, and section order exactly. If the folder is brand new, use `test-plans/cases/create-case.md` as the canonical example.
4. **Verify Admin credentials in `CLAUDE.md`.** The recorded login helper embeds the username and password directly, so empty or placeholder values (`<TODO>`, `change-me`, empty) produce a broken spec. If the Admin row is missing or placeholder, stop and tell the user to run `/test-setup` or add an `| Admin | <username> | <password> |` row, then re-run. Do not invent credentials.
5. **Resolve the Azure DevOps org + project.** Read the `## Azure DevOps` section of `CLAUDE.md`:
   ```
   ## Azure DevOps
   | Key | Value |
   |-----|-------|
   | Organization | <org-name> |
   | Project      | <project-name> |
   ```
   If the section is missing, ask once for Organization and Project, then **offer to append this section to `CLAUDE.md`** so future runs don't re-ask. Do not proceed without both values.
6. **Probe the Azure DevOps MCP.** Call `mcp__ado__core_list_projects`. If the tool is unreachable or not registered, follow `reference/devops-import.md` §1 to register it (`claude mcp add ado -- npx -y @azure-devops/mcp <org>`) and confirm `az login` has been run — then re-probe. Do not continue until the probe succeeds.
7. **Probe the Playwright MCP.** Call `mcp__playwright__browser_navigate` with `url: "about:blank"`. If it errors, stop and tell the user to check `.mcp.json` / register the Playwright MCP (`/test-setup` does this), then re-run.

## Fetch from Azure DevOps

Read `reference/devops-import.md` §2–§4 for the exact tool calls, parameters, and the `Microsoft.VSTS.TCM.Steps` XML structure. The sequence in brief:

1. **Resolve suites.** If a Suite ID was given, use it directly. Otherwise call `mcp__ado__testplan_list_test_suites` with `{ project, planId }` and import **every** suite in the plan (one `.md` per suite).
2. **List test cases per suite.** Call `mcp__ado__testplan_list_test_cases` with `{ project, planid, suiteid }` → collect the test case work item IDs and titles.
3. **Fetch each test case's steps.** Call `mcp__ado__wit_get_work_items_batch_by_ids` (or `mcp__ado__wit_get_work_item` per id) requesting fields `System.Title` and `Microsoft.VSTS.TCM.Steps`. The Steps field is an XML string of `<step>` elements, each holding two `<parameterizedString>` values: **[0] = action**, **[1] = expected result** (HTML-encoded — strip tags and decode entities).

If a suite has zero test cases, skip it and note it in the finishing reply. If a step uses a shared-step `<compref>` or a parameterized `@param` token, follow `reference/devops-import.md` §5–§6.

## Generation — markdown plan (per suite)

Each **suite → one `.md` plan file**; each **ADO test case → one `TC-NN` block**.

1. **File + folder.** Plan title = the suite name. Match it to an existing folder under `test-plans/` (e.g. *"Login Suite"* → `auth/`); if nothing fits, propose a new kebab-case folder and confirm before creating. Save to `test-plans/<folder>/<kebab-suite-name>.md`. If the file exists, ask before overwriting.
2. **Auto-prepend a login TC** as `TC-01` if any imported case needs auth — use the credentials from `CLAUDE.md` (same as `create-test`).
3. **One TC per test case**, in suite order. The TC heading carries the ADO id for traceability:
   ```
   ### TC-02 — Create Service Request (ADO #1234)
   ```
4. **Expand each ADO step** into prefixed actions. Map the action text to a prefix (`NAVIGATE`, `CLICK`, `TYPE`, `SELECT`, `WAIT`, `SNAPSHOT`, `ASSERT`, `API`, `EXTRACT`) using the heuristic table in `reference/devops-import.md` §4. When the action text is ambiguous, keep the verbatim ADO text after a best-guess prefix.
5. **Each ADO expected-result becomes an `ASSERT`** line right after its action. Pure `ValidateStep` steps become a standalone `ASSERT`. Mark the test case's primary outcome `(BLOCKING)` — exactly one BLOCKING assertion per TC.
6. **Snapshot before every `CLICK` or `TYPE`** (RULES.md §2).
7. Estimated duration per RULES.md (~15s simple, ~60s create-and-submit, round to 30s).

## Generation — paired Playwright spec via MCP recording

After each `.md` is written, record the paired `.spec.ts` with real selectors. **Use the exact same recording loop, selector-priority list, bounded fallback, and spec template as the `create-test` skill** — see `../create-test/SKILL.md` → sections *"Generation — paired Playwright spec via MCP recording"*, *"Selector priority"*, *"Bounded fallback"*, and *"Spec file structure"*. Do not reinvent it; that skill is the single source of truth for the recording mechanics.

Two additions specific to DevOps-sourced specs:

- **Traceability header.** Add the ADO link to the spec banner so a failure traces back to the work item:
  ```ts
  // AUTO-RECORDED from test-plans/<folder>/<suite>.md
  // Source: Azure DevOps test plan #<planId>, suite #<suiteId>
  // The .md plan is canonical. AI-repair will patch failing lines in this file.
  ```
- **Per-TC ADO id comment.** Above each `test('TC-NN: ...')` block, emit `// ADO Test Case #<id>: https://dev.azure.com/<org>/<project>/_workitems/edit/<id>`.

Save to `test-plans/<folder>/<kebab-suite-name>.spec.ts`. If the file exists, ask before overwriting (same prompt as the `.md`).

## Multiple suites

When importing a whole plan, process suites **sequentially** — fully author one suite's `.md` + `.spec.ts` before starting the next. Cap live recording at ~2 minutes wall-clock per TC (same as `create-test`); fall through to `// TODO[selector]:` markers for the remainder and note the count.

## Finishing reply

One line per suite, plus an aggregate when more than one suite was imported:

> Imported ADO plan #`<planId>` → `<S>` suite(s), `<C>` test case(s). Created `test-plans/<folder>/<suite>.md` + `.spec.ts` with **`<N>` recorded selectors, `<K>` fallback TODO markers**. Run with `/RunTest <suite>`. (If K>0, expect AI-repair to resolve those K lines on first run.)
