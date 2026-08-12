# API Access — Authenticate, Create & Update

All writes go through the target site's REST API. `scripts/deploy-report.js` performs them in
order (create or update); this document is the contract it implements and what to check if a call
fails.

## Table of contents
- [Authenticate](#authenticate)
- [Create order](#create-order)
- [Create the filter form](#create-the-filter-form)
- [Create the report](#create-the-report)
- [Create the parameters](#create-the-parameters)
- [Updating an existing report (in place)](#updating-an-existing-report-in-place)
- [Verify](#verify)
- [Module route note](#module-route-note)

## Authenticate

```
POST {baseUrl}/api/TokenAuth/Authenticate
Content-Type: application/json
{ "userNameOrEmailAddress": "<user>", "password": "<pass>" }
```

The token is at `result.accessToken` (some deployments return `accessToken` at the top level —
accept both). Send `Authorization: Bearer <token>` on every subsequent call.

## Create order

Create in this order so links resolve:

1. **Filter form** → get its `{name, module}` for `parameterFormPath`.
2. **Report** (`ReportingReport`) with `reportDefinitionXml`, `useCustomParameters:true`,
   `parameterFormPath` → get its `id`.
3. **Parameters** (`ReportingReportParameter`), each referencing the report `id`.

## Create the filter form

Forms are versioned Shesha configuration items. **Three** steps — a newly created form is a
*draft* and will not be resolvable by the report viewer until it is published to *Live*. This flow
is verified against a live v0.43 site; the verb/shape details matter (an earlier `ImportJson`
approach returned HTTP 415 on that deployment).

**a. Create the form item** (draft) — returns `result.id`:
```
POST {baseUrl}/api/services/Shesha/FormConfiguration/Create
Authorization: Bearer <token>
{ "moduleId": "<moduleGuid>", "name": "<form-name>", "label": "<Report title> Filters",
  "description": "Filter form for the <Report title> report" }
```
Resolve `moduleId` from the module name:
`GET {baseUrl}/api/services/app/Module/GetAll` → find the item whose `name` matches, take its `id`.
`Create` 400s if a form with that name already exists in the module — pick a fresh name or delete
the existing one.

**b. Set the markup** — note this is a **PUT**, not POST:
```
PUT {baseUrl}/api/services/Shesha/FormConfiguration/UpdateMarkup
Authorization: Bearer <token>
{ "id": "<formId>", "markup": "<form markup JSON as a string>" }
```
`markup` is the `{components,formSettings}` JSON from [filter-form.md](filter-form.md), stringified.
Success → `{ "result": true }`.

**c. Publish** — set status to Live (`3`) so the runtime resolves it (`GetByName` returns 404 for
drafts). Also a **PUT**; the body uses a jsonLogic `filter` selecting the form id:
```
PUT {baseUrl}/api/services/Shesha/FormConfiguration/UpdateStatus
Authorization: Bearer <token>
{ "filter": "{\"==\":[{\"var\":\"id\"},\"<formId>\"]}", "status": 3 }
```

Confirm with `GET .../FormConfiguration/GetByName?module=<module>&name=<form-name>` → 200 with
`versionStatus: 3`, `isLastVersion: true`, and the markup populated.

Then `parameterFormPath = JSON.stringify({ name: "<form-name>", module: "<module-name>" })`.

## Create the report

```
POST {baseUrl}/api/services/DevExpressReporting/ReportingReport/Create
Authorization: Bearer <token>
{
  "displayName": "Orders by Period",
  "description": "...",
  "reportType": 1,                     // 1 Report | 2 Pivot | 3 Dashboard
  "category": <categoryItemValue>,     // from ReferenceList lookup — do not guess
  "connectionStringName": "Default",
  "orderIndex": 10,
  "showInReportsMenu": true,
  "reportDefinitionXml": "<the XtraReport XML string>",
  "useCustomParameters": true,         // true when a filter form is set
  "parameterFormPath": "{\"name\":\"orders-by-period-filters\",\"module\":\"MyModule\"}"
}
```
Capture `result.id` — the report id used everywhere below and in the viewer URL.

## Create the parameters

One POST per filter (see [data-model.md](data-model.md#reportingreportparameter-fields)):

```
POST {baseUrl}/api/services/DevExpressReporting/ReportingReportParameter/Create
Authorization: Bearer <token>
{
  "reportingReport": { "id": "<reportId>" },
  "internalName": "startDate",
  "displayName": "Start Date",
  "type": { "itemValue": 2 },          // GeneralDataType value (2 = Date)
  "columnName": "CreationTime",
  "parameterOrderIndex": 0,
  "referenceListName": null,
  "referenceListNamespace": null,
  "entityTypeShortAlias": null
}
```
`type` is a reference-list value — send `{ "itemValue": <n> }`. If the CRUD service rejects that
shape, retry with a bare `"type": <n>`. The same ambiguity is confirmed on `ReportingReport`'s own
`reportType`/`category` fields — different deployments want opposite shapes there too (one rejects
bare with a 400 type-conversion error, another rejects wrapped with a JSON parse error) —
`deploy-report.js` handles that pair adaptively (tries one shape, retries with the other on the
specific error signature) rather than hardcoding either. This parameter `type` field isn't wired
through the same adaptive helper yet; if you hit the same wire-shape failure here, apply the
identical retry-with-the-other-shape approach by hand.

## Updating an existing report (in place)

To apply later changes, **update** the existing records — never delete + recreate. Trigger either
by passing the report `id` (`report.id` / `--report-id`), or by name with `--upsert`. Order: form →
report → parameters.

**Find the report by name** (for `--upsert`) — use the generic entity query, not the report
service's `GetAll` (which may 500 on a DTO-mapping bug):
```
GET {baseUrl}/api/services/app/Entities/GetAll
    ?entityType=boxfusion.devexpressreporting.Domain.ReportingReport
    &properties=id displayName
    &filter={"==":[{"var":"displayName"},"<display name>"]}
```
One match → update that id; none → create; several → ask for the exact id.

**Form** — reuse the existing one if present:
```
GET  .../Shesha/FormConfiguration/GetByName?module=<m>&name=<n>   # → result.id (or 404 ⇒ create it)
PUT  .../Shesha/FormConfiguration/UpdateMarkup   { "id": "<formId>", "markup": "<...>" }
PUT  .../Shesha/FormConfiguration/UpdateStatus   { "filter": "{\"==\":[{\"var\":\"id\"},\"<formId>\"]}", "status": 3 }
```
`UpdateMarkup` on a live form keeps it Live (verified).

**Report** — merge changes over the current DTO, keep the same id:
```
GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/Get?id=<reportId>   # existing DTO
PUT {baseUrl}/api/services/DevExpressReporting/ReportingReport/Update              # { ...existing, ...changes }
```
Send the full merged DTO (existing fields + your new `reportDefinitionXml`/metadata) so unset
fields aren't wiped.

**Parameters** — reconcile by `internalName`:
```
GET  .../ReportingReport/GetParameters?reportId=<reportId>        # existing params (with ids)
PUT  .../ReportingReportParameter/Update  { ...existing, ...changes, "id": "<paramId>" }   # match found
POST .../ReportingReportParameter/Create  { ... }                                          # no match
DELETE .../ReportingReportParameter/Delete?id=<paramId>                                     # obsolete (only with --prune-params)
```
By default obsolete parameters are **kept** (logged); pass `--prune-params` to remove ones no longer
in the spec.

## Verify

**Step 1 — fetch back** (cheap sanity check that the write actually landed):
```
GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/Get?id=<reportId>
GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/GetParameters?reportId=<reportId>
```
Confirm the report returns with the XML and the expected parameter count. This proves the row was
saved — it does **not** prove the XML actually loads in the DevExpress report engine.

**Step 2 — actually render it.** This is the real check, and it's scriptable — no browser needed.
Don't go looking for a swagger-documented endpoint for this: on at least one real deployment
`{baseUrl}/swagger/v1/swagger.json` 500s (a generic ABP swagger-generation issue, unrelated to
reporting) while `{baseUrl}/swagger/index.html` still 200s — so swagger is not a reliable way to
*discover* this endpoint even when it half-works. Call the report viewer's own open-document
endpoint directly, confirmed against a live v0.43/DevExpress 23.2 site:
```
POST {baseUrl}/DXXRDV
Authorization: Bearer <token>
Content-Type: application/x-www-form-urlencoded

actionKey=openReport&arg=<reportId>&dxversions={"analytics":"<ver>","devextreme":"<ver>","reporting":"<ver>"}
```
`dxversions` must match the versions the *installed front-end* actually reports (a mismatch is
rejected) — ask the user for the exact JSON their viewer sends (visible in browser devtools on any
report open), or reuse whatever value they've already given you for this site. Don't assume it has
to match the `SerializerVersion`/`Version=` pinned in `build-report-xml.js` — those are independent
numbers and a 23.1.5.0-serialized layout has been confirmed to load fine under a 23.2.13 web viewer;
see the version note in [report-xml.md](report-xml.md#troubleshooting) before "fixing" either one.

**This endpoint always returns HTTP 200 — even on failure** — so check the JSON body, never the
status code:
- **Success**: `"success":true`, `"error":null`, `result.parametersInfo.parameters` lists your
  report's parameters by `Name`, `result.startBuildFaultMessage` is `null`. `result.reportId` here
  is an internal document-session id (not your report's GUID) — ignore it; `result.reportUrl` echoes
  back the report id you passed, which is the useful cross-check.
- **Failure** (bad/unloadable XML, wrong report id, broken data source): `"success":false`,
  `"error":"Exception occurred. See the log file for more details."`, `"result":null`. The message
  itself is generic and gives no detail — don't try to parse a cause out of it; instead work through
  [report-xml.md](report-xml.md#troubleshooting).
- A **non-null `result.startBuildFaultMessage`** alongside `"success":true` means the layout itself
  loaded but document generation failed (e.g. the SQL errored at execution time, not at parse time)
  — that message is specific and worth reading directly.

Only report the report as verified once this call has actually been made against the real deployed
id and returned `"success":true`. A `--dry-run` deploy, or a bare `Get` that only confirms the row
exists, is not a substitute — never claim success without this step.

## Module route note

The front-end calls reports under `/api/services/DevExpressReporting/...` — the default this skill
uses. The backend also registers controllers under the module area `devexpressreportingCommon`; if
`DevExpressReporting` 404s, retry with that segment. `deploy-report.js` accepts
`--module-route <segment>` to override. `{baseUrl}/swagger/index.html` can help you browse routes by
eye, but don't rely on `{baseUrl}/swagger/v1/swagger.json` to inspect them programmatically — it
500s on at least one real deployment (unrelated ABP issue) even though the routes underneath work
fine. If in doubt, just try both segments against a real call.
