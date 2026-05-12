---
name: analyze-workflow-state
description: Analyzes Shesha BPMN workflow ProcessState XML logs to identify execution issues — failed gateways, suspended processes, missing flows, variable problems, and timing anomalies. Use when the user asks to interpret, debug, diagnose, or analyze workflow state XML files, BPMN execution logs, or ProcessState documents. Also use when the user provides a workflow instance ID and asks to check why it failed or what went wrong.
---

# Analyze Workflow State

Interpret Shesha BpmnEngine ProcessState XML logs and report issues, root causes, and recommendations.

## Arguments

The skill accepts optional arguments:

- **File path** — Path to a ProcessState XML file (e.g., `/analyze-workflow-state backend/workflow-state-logs/example1.xml`)
- **Instance ID** — A workflow instance or workflow instance state GUID (e.g., `/analyze-workflow-state 3fa85f64-5717-4562-b3fc-2c963f66afa6`)
- **Backend URL** — URL of the running backend or frontend (e.g., `/analyze-workflow-state 3fa85f64... http://localhost:21021`)

Detect what was provided: a file path (contains `/` or `\` or ends in `.xml`) vs a GUID (matches UUID format). A URL starts with `http`.

## Input Modes

This skill supports two input modes:

1. **XML file** — User provides a ProcessState XML file path
2. **Instance ID** — User provides a workflow instance ID (the state is fetched from the API)

## Step 1: Gather Missing Context

Only ask for information not already provided in the arguments.

**If XML file was provided** — ask using AskUserQuestion:
1. **Workflow Instance ID** — "Do you have the ID of the workflow instance this log belongs to?" (options: "Yes, I'll provide it" / "No, analyze without it")
2. **Backend URL** (if not provided) — "What is the backend URL?" (options: "http://localhost:21021" / "Other")

If the user provides both, proceed to Step 2 (API enrichment). If not, skip to Step 3 (static analysis only).

**If Instance ID was provided** — ask using AskUserQuestion only if backend URL was not provided:
1. **Backend URL** — "What is the backend URL?" (options: "http://localhost:21021" / "Other")

Then proceed to Step 2, using the instance ID to fetch both the workflow state and the BPMN schema.

## Step 2: API Enrichment

Authenticate and fetch data from the running backend.

### 2a. Resolve Backend URL

The user may provide a **frontend URL** (e.g., `https://myapp-adminportal-dev.shesha.app/`) instead of the backend API URL. Detect this:

1. Make a test request: `curl -s -o /dev/null -w "%{content_type}" "{providedUrl}/api/TokenAuth/Authenticate"`
2. If the response Content-Type is `text/html` (not `application/json`), the URL is a frontend. Extract the real backend URL from the HTML:

```bash
curl -s "{frontendUrl}" | grep -oP '"backendUrl"\s*:\s*"([^"]+)"' | head -1
# Or with python:
python -c "
import re, sys
html = sys.stdin.read()
match = re.search(r'\"backendUrl\"\s*:\s*\"([^\"]+)\"', html)
if match: print(match.group(1))
" < <(curl -s "{frontendUrl}")
```

The backend URL is typically in the pattern `https://{app}-api-{env}.shesha.app` while the frontend is `https://{app}-adminportal-{env}.shesha.app`.

### 2b. Authenticate

```bash
TOKEN=$(curl -s -X POST "{baseUrl}/api/TokenAuth/Authenticate" \
  -H "Content-Type: application/json" \
  -d '{"userNameOrEmailAddress":"admin","password":"123qwe"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['result']['accessToken'])")
```

**Note:** Use `python` not `python3` — on Windows `python3` may not exist.

Store the token using the `$TEMP` environment variable (works on both Windows and Unix):

```bash
echo "$TOKEN" > "$TEMP/wf_token.txt"
```

**IMPORTANT:** Never use `/tmp/` directly in bash scripts that also call Python on Windows. Git Bash maps `/tmp` to a different location than Python sees. Always use `$TEMP` in bash and `os.environ['TEMP']` in Python.

### 2c. Resolve the Instance ID — Dual Entity Check

The provided ID may be either a `WorkflowInstance` or a `WorkflowInstanceState` (they can share the same ID). Try both:

**Try as WorkflowInstance first:**

```bash
curl -s "{baseUrl}/api/dynamic/Shesha.Workflow/WorkflowInstance/Crud/Get?id={instanceId}&properties=id workflowDefinition subject status" \
  -H "Authorization: Bearer $TOKEN"
```

- Valid properties: `id`, `workflowDefinition` (returns definition GUID directly), `subject`, `status`
- **Do NOT use:** `workflowDefinition_Id`, `workflowDefinition_Name`, `workflowDefinition_Label`, `errorMessage` — these are NOT valid properties

If this returns a result, the ID is a WorkflowInstance. Extract `workflowDefinition` (the definition ID).

**If WorkflowInstance not found, try as WorkflowInstanceState:**

```bash
curl -s "{baseUrl}/api/dynamic/Shesha.Workflow/WorkflowInstanceState/Crud/Get?id={instanceId}&properties=id processState creationTime" \
  -H "Authorization: Bearer $TOKEN"
```

- Valid properties: `id`, `processState`, `creationTime`
- **Do NOT use:** `workflowInstance_Id`, `workflowInstance` — these are NOT queryable properties

If found as a WorkflowInstanceState, you already have the processState XML. To find the parent WorkflowInstance, fetch all instances and match by checking which one has the same ID or by timestamp correlation.

### 2d. Fetch ProcessState

**If the ID was a WorkflowInstance:**

The WorkflowInstance and its WorkflowInstanceState often share the same ID. Try fetching the state directly:

```bash
curl -s "{baseUrl}/api/dynamic/Shesha.Workflow/WorkflowInstanceState/Crud/Get?id={instanceId}&properties=id processState creationTime" \
  -H "Authorization: Bearer $TOKEN"
```

If that fails, fetch all states and match client-side (the filter on `workflowInstance` does NOT work via the API):

```bash
curl -s "{baseUrl}/api/dynamic/Shesha.Workflow/WorkflowInstanceState/Crud/GetAll?properties=id processState creationTime&maxResultCount=50&sorting=creationTime desc" \
  -H "Authorization: Bearer $TOKEN"
```

Then identify the correct state by matching the creation timestamp or by checking the processState content.

**IMPORTANT:** The following filter syntaxes do NOT work on WorkflowInstanceState:
- `filter=workflowInstance.id%3D%22{id}%22` — `workflowInstance` is not a queryable member
- JsonLogic filter with `workflowInstance.id` — same issue
- `workflowInstance_Id` property — does not exist

### 2e. Get Workflow Definition with BPMN Schema

```bash
curl -s "{baseUrl}/api/services/SheshaWorkflow/WorkflowDefinition/Get?id={definitionId}" \
  -H "Authorization: Bearer $TOKEN"
```

The response includes these key fields:
- `name` — workflow definition name (e.g., "loan-application-workflow")
- `label` — human-readable label (e.g., "Loan Application Workflow")
- `description` — workflow description
- `versionNo` — version number
- `versionStatus` — version status (1=Draft, 3=Live, 5=Retired)
- **`workflowSchema`** — the BPMN XML schema (NOT `configuration` — that field is empty)
- `className` — .NET workflow definition class
- `instanceClassName` — .NET workflow instance class

### 2f. Parse BPMN Schema for Element Names

Parse the `workflowSchema` XML to build an element ID to human-readable name map:

- `<bpmn:startEvent id="..." name="...">` — Start Event names
- `<bpmn:endEvent id="..." name="...">` — End Event names
- `<bpmn:exclusiveGateway id="..." name="...">` — Gateway names
- `<bpmn:parallelGateway id="..." name="...">` — Parallel Gateway names
- `<bpmn:inclusiveGateway id="..." name="...">` — Inclusive Gateway names
- `<bpmn:serviceTask id="..." name="...">` — Service Task names
- `<bpmn:userTask id="..." name="...">` — User Task names
- `<bpmn:sequenceFlow id="..." name="..." sourceRef="..." targetRef="...">` — Flow names and connections
- `<bpmn:subProcess id="..." name="...">` — Sub-Process names

Use this map to replace raw element IDs with their names throughout the analysis output.

### 2g. Extract Shesha Transition Conditions from Extension Elements

**CRITICAL:** Shesha does NOT use standard BPMN `<conditionExpression>` elements. Instead, conditions are stored in **extension element attributes** on `<sequenceFlowSettings>` child elements:

```xml
<bpmn:sequenceFlow id="Flow_1twias4" name="Entity Application" sourceRef="Gateway_0qb5wnk" targetRef="Gateway_15foesy">
  <bpmn:extensionElements>
    <sequenceFlowSettings
      transitionCondition='{"and":[{"==":[{"var":"workflow.model.applicationType"},2]}]}'
      transitionConditionType="jsonLogic"
      transitionConditionJsExpression=""
      updateStatus="false" />
  </bpmn:extensionElements>
</bpmn:sequenceFlow>
```

For each sequence flow, extract:
- `transitionConditionType` — usually `"jsonLogic"` or `"jsExpression"`
- `transitionCondition` — the JsonLogic expression (JSON string)
- `transitionConditionJsExpression` — JavaScript expression (if type is `jsExpression`)

**A flow with `transitionConditionType="jsonLogic"` but NO `transitionCondition` attribute means the condition was never configured** — the engine will evaluate it as false, which is a common cause of gateway failures.

Build a conditions map for all sequence flows and include it in the analysis output.

## Step 3: Analyze the ProcessState XML

Whether the XML came from a file or from the API, analyze all four sections.

### 3a. Top-Level Status

From `<ProcessState>` attributes:
- `status` — `Completed`, `ExecutionSuspended`, `Failed`, `ExecutionFaulted`
- Flag anything other than `Completed`.

### 3b. ProcessPath

Parse `<StateStep>` elements into an execution trace. Check for:

| Issue | Detection | Severity |
|-------|-----------|----------|
| Failed element | `status="Failed"` | Critical |
| Stuck waiting | `status="Waiting"` with no subsequent Succeeded/Failed for same elementID | High |
| Missing outgoing | Succeeded step has no `outgoingID` (not an EndEvent) | High |
| Gateway no valid path | Gateway fails — no outgoing sequence flow condition was true | Critical |
| Parallel gateway incomplete | Waiting but not all incoming tokens arrived | High |

### 3c. ProcessVariables

- Empty `<ProcessVariables />` when gateway conditions reference variables
- Null or unexpected values causing condition failures
- Cross-reference variables against the JsonLogic conditions extracted in Step 2g — flag any `{"var":"..."}` references that don't have corresponding process variables

### 3d. ProcessLog

Key patterns in pipe-delimited log entries:

| Pattern | Meaning |
|---------|---------|
| `Failing Gateway {id}` | No valid outgoing path |
| `Process Step Error occured` | Element threw an error |
| `Checking if Sequence Flow[{id}] is valid` with no selection after | All conditions false |
| `Change Process State status to ExecutionSuspended` | Engine suspended |
| `Change Process State status to ExecutionFaulted` | Unhandled exception |
| `checking for valid Intermediate Catch Event` | Looking for error boundary |

### 3e. ExecutionsTree

- `isEnded="True"` + `isActive="True"` — contradictory state
- `isSuspended="True"` — execution paused
- `activityInstanceId` — which element the execution is stuck on

## Step 4: Present Results

Start with a **succinct summary** (2-3 sentences max) of what happened, then provide the detailed breakdown.

### Output Format

```markdown
## Workflow State Analysis

**Summary:** {1-3 sentence plain-English explanation of what happened and why}

**Instance:** {instance ID}
**State ID:** {state ID if different from instance}
**Status:** {ProcessState status}
**Workflow:** {definition label (name), version vN}
**Definition Class:** {className from definition}

### Execution Trace
| # | Element | Name | Status | Route |
{Use human-readable names from BPMN schema when available, fall back to element ID prefixes}

### Gateway Conditions
{For each gateway in the trace, list its outgoing flows with their conditions}
| Flow | Name | Condition Type | Condition Expression | Result |
{Show whether each condition was present/missing and evaluated true/false}

### Issues Found
{Numbered list with severity, affected element (by name), and description}

### Root Cause Analysis
{Why the workflow reached its current state, referencing specific conditions/data}

### Recommendations
{Actionable steps to resolve}
```

## BPMN Element Type Prefixes

When API schema is unavailable, infer types from ID prefixes:

| Prefix | Type |
|--------|------|
| `StartEvent_*` | Start Event |
| `EndEvent_*` | End Event |
| `Gateway_*` | Gateway |
| `Activity_*` | Task |
| `Flow_*` | Sequence Flow |
| `Event_*` | Intermediate Event |
| `SubProcess_*` | Sub-Process |

## Common Shesha Workflow Failure Patterns

| Pattern | Cause | Fix |
|---------|-------|-----|
| Gateway fails, all flows have `transitionConditionType="jsonLogic"` but no `transitionCondition` | Conditions were never configured in the designer | Add JsonLogic expressions to the sequence flows |
| Gateway fails, conditions reference `workflow.model.X` but ProcessVariables is empty | Workflow model/trigger entity data not being passed to the engine | Check workflow start configuration and model binding |
| Gateway succeeds but picks wrong path | Condition evaluates unexpectedly due to data type mismatch (e.g., string "2" vs number 2) | Check JsonLogic `==` vs `===` and data types |
| Process suspends at a serviceTask | The service task threw an unhandled exception | Check application logs for the exception details |
| Process suspends at a userTask | Expected — user tasks wait for external completion | Not an error unless the task should have auto-completed |
