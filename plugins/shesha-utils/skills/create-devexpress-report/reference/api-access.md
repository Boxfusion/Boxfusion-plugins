# API Access — Authenticate & Create

All writes go through the target site's REST API. `scripts/deploy-report.js` performs them in
order; this document is the contract it implements and what to check if a call fails.

## Table of contents
- [Authenticate](#authenticate)
- [Create order](#create-order)
- [Create the filter form](#create-the-filter-form)
- [Create the report](#create-the-report)
- [Create the parameters](#create-the-parameters)
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
shape, retry with a bare `"type": <n>`.

## Verify

```
GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/Get?id=<reportId>
GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/GetParameters?reportId=<reportId>
```
Confirm the report returns with the XML and the expected parameter count. Then load the report
viewer for `<reportId>` in the app and confirm it renders and the filter drawer shows the form.

## Module route note

The front-end calls reports under `/api/services/DevExpressReporting/...` — the default this skill
uses. The backend also registers controllers under the module area `devexpressreportingCommon`; if
`DevExpressReporting` 404s, retry with that segment. `deploy-report.js` accepts
`--module-route <segment>` to override. Confirm the live path at `{baseUrl}/swagger` when unsure.
