# Data Model — ReportingReport & ReportingReportParameter

The DevExpressReporting backend (`boxfusion.devexpressreporting`) stores each report as a
`ReportingReport` row and each filter as a `ReportingReportParameter` row. This skill writes both
via their Shesha CRUD services.

## Table of contents
- [ReportingReport fields](#reportingreport-fields)
- [ReportingReportParameter fields](#reportingreportparameter-fields)
- [Reference lists](#reference-lists)
- [How a filter reaches the SQL](#how-a-filter-reaches-the-sql)
- [Discovering valid values](#discovering-valid-values)

## ReportingReport fields

Entity `ReportingReport` (table `devxrpt_reportingReports`), DTO `ReportingReportDto`. Set these
in the create payload:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `displayName` | string(255) | yes (practical) | Report title shown in menu/viewer. |
| `description` | string(512) | no | Multiline. |
| `reportType` | int | no | Reference list `Boxfusion.DevExpressReporting.ReportType`: 1=Report, 2=Pivot, 3=Dashboard. |
| `category` | int | **yes** | Reference list `Boxfusion.DevExpressReporting.ReportCategory` — position in the reports menu. Project-specific values. |
| `connectionStringName` | string(255) | **yes** | Named connection from the site's `appsettings` (`ConnectionStrings:<name>`). Usually `Default`. |
| `orderIndex` | int | no | Lower shows first in menu. |
| `showInReportsMenu` | bool | no | `true` to list it in the reports menu. |
| `cronExpression` | string | no | Quartz cron for scheduled send-out. Leave empty. |
| `visibilityRole` | entity ref (`ShaRole`) | no | Role that may see the report; empty = everyone. |
| `reportDefinitionXml` | string (unbounded) | **yes** | The DevExpress XtraReport layout XML — see [report-xml.md](report-xml.md). |
| `useCustomParameters` | bool | no | `true` when using a Shesha filter form instead of the native DX parameter panel. Set `true` when `parameterFormPath` is set. |
| `parameterFormPath` | string | no | JSON-serialized `FormIdentifier` — `{"name":"<form-name>","module":"<module>"}` — pointing at the Shesha filter form. |
| `reportState`, `generatedFieldsList`, `customFilterView` | string | no | Leave empty for new reports. |

> `parameterFormPath` is stored as a **JSON string**, not an object. The viewer `JSON.parse`s it
> into a `FormIdentifier`. Write exactly `{"name":"report-x-filters","module":"MyModule"}`.

> **`category`/`reportType` can fail two different ways, and seeding a missing reference-list item
> only fixes one of them.** Failure mode 1 — the value is rejected at request-parse time
> (`"Error converting value 1 to type 'ReferenceListItemValueDto'"`, a 400) — is a wire-shape
> mismatch; `deploy-report.js` now retries automatically with the value wrapped as
> `{ "itemValue": N }` (or unwrapped, whichever wasn't tried first). Failure mode 2 — a 500 with
> `"Error mapping types... Destination Member: Category"` *after* the request parsed fine — is a
> genuine AutoMapper configuration bug in that deployment's `ReportingReport → ReportingReportDto`
> mapping, confirmed to persist even after the referenced item was created via
> `ReferenceListItem/Create` (so "the item doesn't exist yet" is not always the explanation, and
> adding it is not always the fix). If failure mode 2 shows up, the practical workaround is to
> **omit the field from the payload entirely** (leave it unset/null) rather than continuing to seed
> reference data that won't resolve the mapping error — the report still deploys and renders fine,
> just uncategorized / defaulting to the `Report` type, until someone fixes the mapping profile
> server-side.

## ReportingReportParameter fields

Entity `ReportingReportParameter`, DTO `ReportingReportParameterDto`. One row per filter:

| Field | Type | Notes |
|-------|------|-------|
| `reportingReport` | entity ref (Guid) | `{ "id": "<reportId>" }`. Links the parameter to the report. |
| `internalName` | string(255) | **Must equal** the SQL `@param` name AND the filter-form field `propertyName`. The alignment key. |
| `displayName` | string(255) | Label shown to the user. |
| `type` | int | Reference list `Boxfusion.DevExpressReporting.DataType` — see `GeneralDataType` below. |
| `columnName` | string(300) | The DB column the filter targets. |
| `description` | string(512) | Optional. |
| `hideParameter` | bool | `true` hides it from the filter UI (fixed/default value). |
| `parameterValue` | string | Optional default value. |
| `parameterOrderIndex` | int | Order in the filter form; else alphabetical. |
| `referenceListName`, `referenceListNamespace` | string | Set for reference-list parameters. |
| `entityTypeShortAlias` | string | Set for entity-reference parameters; resolve the type from the site (see [Discovering valid values](#discovering-valid-values)) — do not hardcode. |

## Reference lists

`GeneralDataType` (`Boxfusion.DevExpressReporting.DataType`) — value used in parameter `type`:

| Name | Value | Filter-form input |
|------|-------|-------------------|
| Guid | 0 | textField |
| Text | 1 | textField |
| Date | 2 | dateField |
| Time | 3 | timeField |
| DateTime | 4 | dateField (showTime) |
| Boolean | 5 | checkbox / switch |
| Numeric | 6 | numberField |
| Enum | 7 | dropdown |
| ReferenceList | 8 | dropdown (refList) |
| MultiValueReferenceList | 9 | dropdown (multiple, refList) |
| EntityReference | 10 | entityPicker / autocomplete |
| StoredFile | 11 | (rare — skip for filters) |
| List | 12 | (rare — skip for filters) |

`RefListReportType` (`Boxfusion.DevExpressReporting.ReportType`): 1=Report, 2=Pivot, 3=Dashboard.

`ReportCategory` (`Boxfusion.DevExpressReporting.ReportCategory`): project-specific — look it up
(below). Do not guess the numeric value.

## How a filter reaches the SQL

The chain must line up by name across four places:

```
SQL:        ... WHERE (@startDate IS NULL OR o.CreationTime >= @startDate)
XtraReport: report Parameter  Name="startDate"  (bound into the query parameter)
Parameter:  ReportingReportParameter.internalName = "startDate", columnName = "CreationTime"
Form:       ConfigurableForm field  propertyName = "startDate"
```

At runtime the viewer reads the filter form's values, maps each onto the DevExpress report
parameter of the same name (`setParameterValue("startDate", value)`), and rebuilds the document;
the SQL then filters using `@startDate`. If any name differs, the filter silently does nothing.

## Discovering valid values

**Nothing project-specific is hardcoded.** Categories, reference-list names/modules, entity types,
FK columns, and reflist item values are all resolved from the **target site's APIs** at build time.

**Use the bundled `scripts/discover-metadata.js`** — it does all of this for you (auth + the calls
below) and prints JSON:
```bash
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' entities [substr]   # find a table/entity
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' entity <ClassName>  # table, module, entity-FK props (fkColumn), reflist props
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' reflist <name>       # full reflist name(s)+module+items — warns on duplicates
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' category             # ReportCategory items
```
> `entity <ClassName>` matches on the **short** class name only (e.g. `VerificationCampaign`), not
> the fully-qualified C# namespace — it does an exact case-insensitive match against `className` as
> returned by `EntityConfig/GetMainDataList`. Passing the full path (e.g.
> `Shesha.AssetManagement.Domain.VerificationCampaigns.VerificationCampaign`) returns a false
> `Entity "..." not found` even when the entity genuinely exists. This is the *opposite* of what a
> report parameter's `entityTypeShortAlias` needs — that field **does** want the full namespace path
> (see the [ReportingReportParameter fields](#reportingreportparameter-fields) table above). Don't
> conflate the two: short name for this discovery command, full path for the actual spec field.

`entity` returns each entity property's `fkColumn` (Shesha convention `<Nav>Id`) and, for
reference-list properties, the full `referenceListName`/`referenceListModule` — feed these straight
into the report spec. `reflist` returns **every** match with its items and warns when several exist
(their item values can differ — pick the one for the column you are mapping, or resolve labels in
SQL via `dbo.Frwk_GetRefListItem('<module>','<ShortName>', <col>)` to sidestep the ambiguity).

The endpoints it calls (if you prefer to do it by hand): `POST /api/TokenAuth/Authenticate`
→ `result.accessToken`, then `Authorization: Bearer <token>` on:

**Report category** (`ReportType`/`ReportCategory` are the DevExpressReporting module's own
reflists) — enumerate items via the `Entities/GetAll` pattern (the `ReferenceList/GetItems`
endpoint may 500 on some builds):
```
# find the reference list id
GET {baseUrl}/api/services/app/Entities/GetAll?entityType=Shesha.Framework.ReferenceList
    &quickSearch=ReportCategory
# then its items
GET {baseUrl}/api/services/app/Entities/GetAll?entityType=Shesha.Framework.ReferenceListItem
    &filter={"==":[{"var":"referenceList"},"<reflistId>"]}
```
Show the user the `item`/`itemValue` pairs and confirm which category to use — do not assume a value.

**Reference-list filter** (data type 8/9) — resolve the **full name + module** for the filter's
reference list; never hardcode a namespace:
```
GET {baseUrl}/api/services/app/Entities/GetAll?entityType=Shesha.Framework.ReferenceList
    &quickSearch=<shortName>
```
Read the returned full `name` (e.g. `<Module>.<ShortName>`) and `module` — these become the
parameter's `referenceListName`/`referenceListNamespace` (and the form's `referenceListId`). Verify
item values via the `ReferenceListItem` query above so the SQL predicate uses real values.

**Entity filter** (data type 10) — resolve the entity type and a display property:
```
GET {baseUrl}/api/services/app/EntityConfig/GetMainDataList?maxResultCount=10000&sorting=className
```
Match the class by `className`; use its type name/alias for `entityTypeShortAlias`, then pick a
*candidate* display property from `GET {baseUrl}/api/ModelConfigurations/{classId}` (e.g. a
name/title field) — but don't stop there. The C# property name shown there is frequently **not**
the actual JSON field (the API is camelCase, and Shesha's synthetic `_displayName` field often isn't
what `ModelConfigurations` suggests at all). Confirm the property really resolves before using it —
see [filter-form.md](filter-form.md#verify-entitydisplayproperty-before-trusting-it) for the exact
`Entities/GetAll` check and the real incident that made this step mandatory, not optional.

If a value can't be resolved on the target site, stop and ask — never guess names or item values.

**Connection strings** — the report data source uses a **named** connection resolved server-side
by `ConnectionStringsProvider` (it registers `Default` from `ConnectionStrings:Default`). Use
`Default` unless the user names another connection configured in the site's `appsettings`.

> SKILL.md lists the literal MSSQL connection string as "optional" to gather up front, on the
> reasoning that server-side name resolution makes the literal baked into the XML irrelevant. Treat
> that as true for the *deployed, working* case only — get the real literal (server + database, not
> a guess) whenever: (a) you're validating/building the SQL directly against the database yourself
> rather than going through the `generate-sql-query` skill, since that path needs a real,
> connectable string regardless of what the target's `Default` resolves to; or (b) you can't yet
> confirm named resolution is actually behaving as documented on this particular deployment. Don't
> assume "the name matters more than the string" is a universal safety net — ask for the real
> connection string rather than leaving a placeholder in the XML if there's any doubt.
