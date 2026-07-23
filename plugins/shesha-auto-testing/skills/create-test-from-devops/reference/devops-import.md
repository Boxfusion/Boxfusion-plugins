# Azure DevOps Import Reference

Detailed mechanics for pulling test cases out of Azure DevOps and turning their steps into the prefixed plan format. The SKILL.md body covers the workflow; this file covers the parts that are fiddly or non-obvious.

## Contents

1. Connecting the Azure DevOps MCP
2. Resolving org / project / plan / suite
3. Fetch sequence (exact tool calls)
4. Mapping ADO step text → plan prefixes
5. Parsing the `Microsoft.VSTS.TCM.Steps` XML
6. Parameterized data & shared steps
7. Traceability back to the work item

---

## 1. Connecting the Azure DevOps MCP

The skill talks to Azure DevOps through Microsoft's official MCP server, the npm package `@azure-devops/mcp`. It takes the **organization name** as its launch argument and authenticates through the Azure CLI.

**Prerequisites the user must satisfy once:**
- Azure CLI installed and signed in: `az login` (the MCP server reuses that token). Without it, every tool call returns an auth error.
- Membership in the Azure DevOps organization with read access to Test Plans.

**Register the server with Claude Code** (server name `ado`, so tools surface as `mcp__ado__*`):

```bash
claude mcp add ado -- npx -y @azure-devops/mcp <ORG_NAME>
```

`<ORG_NAME>` is the org slug from the URL `https://dev.azure.com/<ORG_NAME>`. Optionally scope the server to just the test-plan + work-item domains to keep the tool list small:

```bash
claude mcp add ado -- npx -y @azure-devops/mcp <ORG_NAME> -d test-plans work-items core
```

After adding, confirm with `claude mcp list` (look for a `ado` line) and re-probe with `mcp__ado__core_list_projects`. If the add command fails, surface stderr verbatim — usual causes are the `claude` CLI not on PATH, or `az login` not having been run.

## 2. Resolving org / project / plan / suite

- **Organization + Project** come from the `## Azure DevOps` section of `CLAUDE.md` (see SKILL.md pre-flight §5). The org is baked into the MCP server registration; the project is passed as a parameter on every call.
- **Plan ID** is supplied by the user. To let the user discover it, `mcp__ado__testplan_list_test_plans` with `{ project, filterActivePlans: true, includePlanDetails: true }` lists plans with their ids and names.
- **Suite ID** is optional. `mcp__ado__testplan_list_test_cases` requires **both** `planid` and `suiteid`, so a suite can never be queried without its parent plan id — this is why the user always gives a Plan ID, and Suite ID only narrows it.

## 3. Fetch sequence (exact tool calls)

Parameter names are case-sensitive and differ between tools (`planId` vs `planid`) — copy them exactly.

```
# 1. (optional) discover plans
mcp__ado__testplan_list_test_plans   { project, filterActivePlans: true, includePlanDetails: true }

# 2. list suites in the chosen plan  (skip if user gave a Suite ID)
mcp__ado__testplan_list_test_suites  { project, planId }

# 3. list test cases in each suite  → returns work item ids + titles
mcp__ado__testplan_list_test_cases   { project, planid, suiteid }

# 4. fetch the steps for those ids (batch is cheaper than one-by-one)
mcp__ado__wit_get_work_items_batch_by_ids {
  project,
  ids: [ <testCaseId>, ... ],
  fields: ["System.Title", "Microsoft.VSTS.TCM.Steps", "Microsoft.VSTS.TCM.Parameters", "Microsoft.VSTS.TCM.LocalDataSource"]
}
```

`Microsoft.VSTS.TCM.Parameters` and `Microsoft.VSTS.TCM.LocalDataSource` are only present on parameterized (data-driven) test cases — request them so §6 can resolve `@param` tokens, and ignore them when absent.

## 4. Mapping ADO step text → plan prefixes

ADO action text is free-form English written by a tester. Apply these heuristics, in order, to choose a prefix. This is a **high-freedom** judgement call — when nothing matches cleanly, emit the best-guess prefix followed by the verbatim ADO text so the recording loop and AI-repair have the original intent.

| ADO action text contains… | Prefix | Example emitted plan line |
|---|---|---|
| "navigate to", "go to", "open the … page", a URL | `NAVIGATE` | `NAVIGATE {APP_URL}/login` |
| "click", "press", "tap", "select the … button/link/tab", "choose … button" | `CLICK` | `CLICK Save button` |
| "enter", "type", "input", "fill", "provide … in/into …", "set … to" | `TYPE` | ``TYPE Search field with `service request` `` (for a credential field, write it abstractly — ``TYPE Username field with the admin username`` — never the literal value) |
| "select … from", "choose … from the dropdown/list", "pick" | `SELECT` | `SELECT Country — choose South Africa` |
| "wait", "until", "loading", "spinner disappears" | `WAIT` | `WAIT for the grid to load` |
| "log in", "sign in", "authenticate" with credentials | (auto login TC) | handled by the prepended login `TC-01` |
| the **expected-result** column, or action text starting "verify", "confirm", "ensure", "should see", "is displayed", "check that" | `ASSERT` | `ASSERT the success toast "Saved" is visible` |

Rules:
- **Every step's expected-result string becomes its own `ASSERT` line**, placed immediately after the action line for that step.
- A step with an empty action but a non-empty expected result (a `ValidateStep`) becomes a standalone `ASSERT`.
- Insert a `SNAPSHOT — <what the next action targets>` line before every `CLICK` and `TYPE` (RULES.md §2).
- Choose exactly one `ASSERT (BLOCKING)` per TC — the assertion that proves the test case's headline outcome (usually the last/most important expected result).

## 5. Parsing the `Microsoft.VSTS.TCM.Steps` XML

The field is an XML string. Shape:

```xml
<steps id="0" last="3">
  <step id="2" type="ActionStep">
    <parameterizedString isformatted="true">&lt;DIV&gt;&lt;P&gt;Click the Login button&lt;/P&gt;&lt;/DIV&gt;</parameterizedString>
    <parameterizedString isformatted="true">&lt;DIV&gt;&lt;P&gt;The dashboard is shown&lt;/P&gt;&lt;/DIV&gt;</parameterizedString>
    <description/>
  </step>
  <step id="3" type="ValidateStep">
    <parameterizedString isformatted="true">&lt;P&gt;Header reads "Welcome"&lt;/P&gt;</parameterizedString>
    <parameterizedString isformatted="true"/>
  </step>
</steps>
```

To extract clean text per step:
1. Iterate `<step>` elements **in document order** — that is the test execution order.
2. The **first** `<parameterizedString>` is the **action**; the **second** is the **expected result** (may be empty).
3. The inner value is HTML-encoded (`&lt;DIV&gt;` etc.). Decode HTML entities, then strip all tags (`<DIV>`, `<P>`, `<BR>`, `<SPAN>`, …) and collapse whitespace to get plain text.
4. `type="ActionStep"` → action (+ optional expected result). `type="ValidateStep"` → treat as expected-result-only (a standalone `ASSERT`).
5. An empty or missing Steps field means the test case has no manual steps — emit a single `TC` with a `// TODO[steps]: ADO test case #<id> has no steps` note and move on; don't fail the whole import.

Do the decode/strip with normal text handling — no external library needed.

## 6. Parameterized data & shared steps

**Parameterized steps.** Data-driven test cases embed `@paramName` tokens in the action/expected text, with values in `Microsoft.VSTS.TCM.Parameters` (the parameter names) and `Microsoft.VSTS.TCM.LocalDataSource` (an XML/CSV table of rows). If present:
- Use the **first data row** to substitute each `@paramName` with its concrete value (e.g. `@country` → `South Africa`). One concrete plan is enough for an e2e smoke; note in the finishing reply that only row 1 was used.
- **Exception — credential params.** If a `@paramName` resolves to a login username or password (`@username`, `@password`, `@pwd`, …), do **not** inline the value. Keep the plan step abstract (*the admin username* / *the admin password*) and let the spec read it from `process.env` — the concrete value stays in `.env`, never in a committed file.
- If a token can't be resolved, keep the literal `@paramName` and add a `// TODO[param]: <token>` marker so AI-repair / the author can fill it.

**Shared steps.** A reused step block appears as a `<compref ref="<sharedStepWorkItemId>">` element instead of a `<step>`. To expand it, fetch that work item (`mcp__ado__wit_get_work_item { id: <ref>, fields: ["Microsoft.VSTS.TCM.Steps"] }`) and inline its steps at that position. If expansion fails, emit a `// TODO[shared-step]: ADO #<ref>` marker and continue.

## 7. Traceability back to the work item

Keep the link from generated artefact → ADO work item so a failing test is easy to triage:
- Plan: append `(ADO #<id>)` to each `TC-NN` heading.
- Spec banner: `// Source: Azure DevOps test plan #<planId>, suite #<suiteId>`.
- Per-TC comment in the spec: `// ADO Test Case #<id>: https://dev.azure.com/<org>/<project>/_workitems/edit/<id>`.

The work item edit URL pattern is `https://dev.azure.com/<org>/<project>/_workitems/edit/<id>`.
