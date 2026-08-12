# Report Definition XML — DevExpress v23.1

The `ReportDefinitionXml` is a DevExpress **XtraReport** layout serialized by
`XtraReportsLayoutSerializer` (version **23.1.5.0**, pinned by the module's
`DevExpress.AspNetCore.Reporting` package). The backend loads it with
`XtraReport.LoadLayoutFromXml`, so it must be a valid layout for that serializer version.

This format is **reverse-engineered from real reports** saved by the v23.1 designer (see the
`ReportsExamples` used to build this skill). `scripts/build-report-xml.js` emits it and is the
single source of truth — correct the format there if a serializer detail changes.

## Table of contents
- [spec.json shape](#specjson-shape)
- [Envelope](#envelope)
- [Report parameters + ObjectStorage](#report-parameters--objectstorage)
- [SqlDataSource (Base64 blob)](#sqldatasource-base64-blob)
- [Report type — tabular](#report-type--tabular)
- [Pivot / Dashboard](#pivot--dashboard)
- [Type name reference](#type-name-reference)
- [Troubleshooting](#troubleshooting)

## spec.json shape

```jsonc
{
  "reportName": "OrdersByPeriod",
  "title": "Orders by Period",
  "type": "Report",                        // "Report" | "Pivot" | "Dashboard"
  "dataSourceName": "OrdersData",          // SqlDataSource Name (any identifier)
  "connectionStringName": "Default",       // Connection Name — resolved server-side
  "connectionString": "Data Source=...;Initial Catalog=...;User=...;Password=...;MultipleActiveResultSets=True;TrustServerCertificate=True",
  "queryName": "OverviewData",             // query + result-view name = data member
  "landscape": false, "pageWidth": 850, "pageHeight": 1100,
  "theme": {                               // OPTIONAL — omit for the polished default look
    "primaryColor": "#2E4A62", "accentColor": "#E8863C", "headerTextColor": "#FFFFFF",
    "bandColor": "#EEF2F6", "textColor": "#333333", "gridColor": "#D9DEE4",
    "fontFamily": "Arial", "titleSize": 16, "chartPalette": "Nature Colors",
    "logoBase64": "<base64 png/jpg, optional>", "footerText": "Org name / footer line"
  },
  "sql": "SELECT o.Id, o.OrderNo, o.Total, o.CreationTime FROM tbl_Orders o WHERE (@dateFrom IS NULL OR o.CreationTime >= @dateFrom) AND (@statuses IS NULL OR o.StatusLkp IN (SELECT Value FROM string_split(@statuses,',')))",
  "columns": [                             // SELECT output, in display order
    { "field": "OrderNo",      "caption": "Order No", "type": "System.String" },
    { "field": "Total",        "caption": "Total",    "type": "System.Decimal",  "format": "{0:n2}" },
    { "field": "CreationTime", "caption": "Created",  "type": "System.DateTime", "format": "{0:d}" }
  ],
  "parameters": [                          // report params + query params + filter fields
    { "name": "dateFrom", "displayName": "Start Date", "type": "System.DateTime", "dataType": 2, "columnName": "CreationTime", "default": "01/01/2020", "orderIndex": 0 },
    { "name": "statuses", "displayName": "Statuses",   "type": "System.String",   "dataType": 9, "multiValue": true, "columnName": "StatusLkp", "orderIndex": 1,
      "referenceListName": "OrderStatus", "referenceListNamespace": "MyModule" }
  ],
  "pivot":     { "rows": ["Region"], "columns": ["Year"], "data": [{ "field": "Total", "summary": "Sum", "format": "{0:n2}" }] },
  "dashboard": { "argument": "Region", "series": [{ "field": "Total", "summary": "COUNT()" }], "kpis": [{ "field": "Total", "caption": "Total", "summary": "Sum", "format": "{0:n2}" }] },
  "charts":    [{ "title": "By Status", "dataMember": "StatusCounts", "chartType": "pie", "argument": "Status", "series": [{ "caption": "Orders", "valueField": "Cnt" }] }],  // type:"Report" only — see "Charts on a tabular report" below
  "filtersSummaryExpression": "Max([FiltersSummary.SummaryText])"  // OPTIONAL — see "Applied filters summary" below
}
```

**Multiple queries + multiple charts** (e.g. a bar chart and a pie from different data): use
`queries[]` instead of a single `sql`, and `dashboard.charts[]` instead of a single chart. Every
query declares all report parameters, so `@param` filters bind in each:
```jsonc
{
  "type": "Dashboard", "dataSourceName": "CasesData",
  "queries": [
    { "name": "MonthlyData", "sql": "SELECT ... GROUP BY month", "columns": [ ... ] },
    { "name": "AgentData",   "sql": "SELECT TOP 10 Agent, COUNT(*) AS Cnt ... GROUP BY Agent", "columns": [ ... ] }
  ],
  "dashboard": {
    "kpis": [ { "caption": "Total", "field": "CasesLogged", "dataMember": "MonthlyData", "summary": "Sum" } ],
    "charts": [
      { "title": "Logged vs Resolved", "dataMember": "MonthlyData", "chartType": "bar", "argument": "Period",
        "series": [ { "caption": "Logged", "valueField": "CasesLogged" }, { "caption": "Resolved", "valueField": "CasesResolved" } ] },
      { "title": "Top Agents", "dataMember": "AgentData", "chartType": "pie", "argument": "Agent",
        "series": [ { "caption": "Cases", "valueField": "Cnt" } ] }
    ]
  }
}
```
Each chart's `dataMember` names the query it binds to; `chartType` ∈ `bar | stackedBar | line |
area | pie | doughnut` (or set `viewType` to a raw DevExpress series-view name). KPIs may set their
own `dataMember`. Charts stack vertically under the KPI row.

`columns[].type` / `parameters[].type` use .NET type names; `parameters[].dataType` is the
`GeneralDataType` value used for the filter form (see [data-model.md](data-model.md)). `multiValue`
params render as `string_split` list filters.

## Styling (theme)

Every report is styled **by default** — no `theme` needed. The builder applies a professional look
to all three types via `resolveTheme` + shared `headerControls`/`footerControls`:
- **Report header** on every report: title in the primary colour, optional logo (top-right),
  optional description subtitle, a "Generated: …" timestamp, and an accent rule.
- **Footer** (bottom margin): accent rule, optional footer/organization text, `Page X of Y`.
- **Tabular**: header row filled with the primary colour + white bold text + padding; detail rows
  with a light bottom border, padding, and right-aligned numeric columns.
- **Dashboard**: KPI "cards" (banded background, primary text) above a palette-coloured chart.
- **Pivot**: themed header/footer around the grid.

**To follow a supplied design**, pass a `theme` object (all keys optional; see the `spec.json`
example). Colours accept `#RRGGBB`, `r,g,b`, `a,r,g,b`, or a named colour — the builder normalises
to DevExpress `a,r,g,b`. `logoBase64` embeds a logo; `chartPalette` is any DevExpress palette name.
Nothing about the theme is hardcoded to a project — defaults are brand-neutral and every value is
overridable.

> **`chartPalette` names are not validated before deploy.** A bad name doesn't fail at build time —
> it fails at render time with `"error":"PaletteException occurred..."` in the DXXRDV response.
> Confirmed **valid** by an actual successful render: `Nature Colors`, `Pastel Kit`. Confirmed
> **invalid** the same way: `Pop`, `Dark`, `Office2007` (these look like plausible DevExpress
> palette names but threw `PaletteException` on a real deployment). If you want variety across
> reports and aren't certain a given name is valid on the target's DevExpress version, either stick
> to the two confirmed-good names above or verify a new one via the DXXRDV render check
> ([api-access.md](api-access.md#verify)) before telling the user it worked.

> **Fonts must exist on the report server.** The default `Arial` renders on both Windows and
> Linux/Skia hosts. Windows-only fonts (e.g. `Segoe UI`) throw an `ArgumentException` at document
> build on Linux servers ("Document creation was cancelled due to server error"). Only set
> `fontFamily` to a font you know is installed on the target's render host.

## Envelope

Root uses the **fully assembly-qualified** `ControlType`; **bands and controls use short names**
(`TopMarginBand`, `ReportHeaderBand`, `PageHeaderBand`, `DetailBand`, `BottomMarginBand`, `XRLabel`,
`XRTable`, `XRTableRow`, `XRTableCell`, `XRPivotGrid`, `XRChart`). The data source is `#Ref-0`; the
report root is `Ref="1"`.

```xml
<?xml version="1.0" encoding="utf-8"?>
<XtraReportsLayoutSerializer SerializerVersion="23.1.5.0" Ref="1"
    ControlType="DevExpress.XtraReports.UI.XtraReport, DevExpress.XtraReports.v23.1, Version=23.1.5.0, Culture=neutral, PublicKeyToken=b88d1754d700e49a"
    Name="{reportName}" Margins="50, 50, 50, 50" PageWidth="850" PageHeight="1100"
    Version="23.1" DataSource="#Ref-0">
  <Parameters> ... </Parameters>
  <Bands> ... </Bands>
  <ParameterPanelLayoutItems> ... </ParameterPanelLayoutItems>
  <ComponentStorage> ... </ComponentStorage>   <!-- the Base64 SqlDataSource, Ref="0" -->
  <ObjectStorage> ... </ObjectStorage>          <!-- parameter type table -->
</XtraReportsLayoutSerializer>
```

## Report parameters + ObjectStorage

Scalar parameters carry a `Type="#Ref-N"` that points at an `<ObjectStorage>` entry declaring the
.NET type; a default goes in `ValueInfo`. Multi-value parameters instead use
`AllowNull="true" MultiValue="true"` and **no** `Type`.

```xml
<Parameters>
  <Item1 Ref="3" Description="Start Date" ValueInfo="01/01/2020" Name="dateFrom" Type="#Ref-2" />
  <Item2 Ref="4" Description="Statuses" AllowNull="true" MultiValue="true" Name="statuses" />
</Parameters>
...
<ParameterPanelLayoutItems>
  <Item1 Ref="60" LayoutItemType="Parameter" Parameter="#Ref-3" />
  <Item2 Ref="61" LayoutItemType="Parameter" Parameter="#Ref-4" />
</ParameterPanelLayoutItems>
...
<ObjectStorage>
  <Item1 ObjectType="DevExpress.XtraReports.Serialization.ObjectStorageInfo, DevExpress.XtraReports.v23.1"
         Ref="2" Content="System.DateTime" Type="System.Type" />
</ObjectStorage>
```

One `ObjectStorage` entry per **distinct** scalar type (shared across params of that type).

## SqlDataSource (Base64 blob)

The data source is a single `ComponentStorage` item whose `Base64` attribute is the
UTF-8→Base64 encoding of this inner XML. This is the critical, non-obvious part: the designer does
**not** expand the data source in the layout — it stores it as this blob.

```xml
<ComponentStorage>
  <Item1 Ref="0" ObjectType="DevExpress.DataAccess.Sql.SqlDataSource,DevExpress.DataAccess.v23.1"
         Name="{dataSourceName}" Base64="{base64(innerXml)}" />
</ComponentStorage>
```

Inner XML (before Base64):

```xml
<SqlDataSource Name="{dataSourceName}">
  <Connection Name="{connectionStringName}" ConnectionString="{connString};XpoProvider=MSSqlServer" />
  <Query Type="CustomSqlQuery" Name="{queryName}">
    <Parameter Name="dateFrom" Type="DevExpress.DataAccess.Expression">(System.DateTime)(?dateFrom)</Parameter>
    <Parameter Name="statuses" Type="DevExpress.DataAccess.Expression">(System.String)(?statuses)</Parameter>
    <Sql>{SQL with @param tokens, XML-escaped}</Sql>
  </Query>
  <ResultSchema>
    <DataSet Name="{dataSourceName}">
      <View Name="{queryName}">
        <Field Name="OrderNo" Type="String" />
        <Field Name="Total" Type="Decimal" />
      </View>
    </DataSet>
  </ResultSchema>
  <ConnectionOptions CloseConnection="true" />
</SqlDataSource>
```

Rules confirmed from real reports:
- Query parameter expression is `({netType})(?{name})`; the SQL references the same names as
  `@{name}`. Multi-value filters use `@p IS NULL OR col IN (SELECT Value FROM string_split(@p,','))`.
- `ResultSchema` field types are the short names in [Type name reference](#type-name-reference).
  Alias every SELECT column so the field names match the bindings.
- `ConnectionString` embeds the DB connection with `;XpoProvider=MSSqlServer`. The backend's
  `ConnectionStringsProvider` also resolves the `Connection Name` server-side and `PrepareReport`
  overrides the string from `appsettings`, so the name (`Default`) is what ultimately matters.

## Report type — tabular

Bands: `TopMarginBand`, `ReportHeaderBand` (title `XRLabel`), `PageHeaderBand` (one `XRTable` row of
bold header cells), `DetailBand` (one `XRTable` row of data cells), `BottomMarginBand`. Each detail
cell binds via an expression to the **view-qualified** column, matching real reports:

```xml
<Item1 Ref="..." ControlType="XRTableCell" Name="dc_Total" Weight="250" TextFormatString="{0:n2}">
  <ExpressionBindings>
    <Item1 Ref="..." EventName="BeforePrint" PropertyName="Text" Expression="[OverviewData.Total]" />
  </ExpressionBindings>
</Item1>
```

### Charts on a tabular report

A `Report`-type spec may also carry `charts[]` — the same shape as `dashboard.charts[]` (see
[Pivot / Dashboard](#pivot--dashboard) below for the series shapes). Unlike Dashboard, tabular
reports keep their detail table; each chart is rendered into the **ReportHeader** band, stacked
below the title/accent line and above the page-header/detail table, so it prints once above the
listing rather than replacing it:

```jsonc
{
  "type": "Report",
  "dataSourceName": "CaseOverviewData",
  "queries": [
    { "name": "CaseOverviewQuery", "sql": "SELECT ... FROM SM_Cases ...", "columns": [ ... ] },
    { "name": "ChannelQuery", "sql": "SELECT Channel, COUNT(*) AS CaseCount FROM ... GROUP BY Channel", "columns": [ ... ] }
  ],
  "columns": [ /* table columns, bound to the primary (first) query */ ],
  "charts": [
    { "title": "Cases Logged by Channel", "dataMember": "ChannelQuery", "chartType": "pie",
      "argument": "Channel", "series": [ { "caption": "Cases", "valueField": "CaseCount" } ] }
  ]
}
```

A chart's `dataMember` names the query it binds to (defaults to the primary query if omitted); use
a second entry in `queries[]` when the chart aggregates data the table doesn't (e.g. counts grouped
by a column the table doesn't show). Every query in `queries[]` receives all of `spec.parameters`,
so report filters apply to the chart the same way they apply to the table. The ReportHeader band's
height grows automatically to fit the stacked chart(s).

**Updating an existing tabular report to add a chart**: rebuild its full spec (table columns +
queries + the new `charts[]`) and redeploy with the report's `id` — `ReportingReport/Update` merges
the new `reportDefinitionXml` over the existing DTO, so parameters/filter form are untouched (see
[api-access.md](api-access.md#updating-an-existing-report-in-place)). This requires reconstructing
the spec (from the requirement + `discover-metadata.js`) since only the rendered XML, not the
original spec, is stored server-side. If a report's XML was hand-edited outside this skill (e.g. in
the DevExpress designer) and must be preserved byte-for-byte apart from the addition, injecting the
chart XML directly into the fetched `reportDefinitionXml` is the fallback — but that path is
one-off and not what `build-report-xml.js` does.

### Applied filters summary

`spec.filtersSummaryExpression` adds one more line to the ReportHeader, below the title/description
and above the "Generated: …" timestamp, showing the currently-applied filter selections (or "All"
per filter when nothing/everything is selected) — e.g. "Category: All | Case Type: All | Status:
Open, Closed | Priority: All | Channel: All". Works on any report type (`Report`, `Pivot`,
`Dashboard`); on tabular reports it composes correctly with `charts[]` (the charts are pushed down
to make room).

**Compute the summary text in SQL, not in the DevExpress expression** — the report `Parameters` you
bind a filter form to hold the raw comma-joined string the SQL side consumes (e.g. `"1,2"`), not
human-readable labels, and DevExpress's report-expression language has no real string-list/lookup
functions to turn that into "Category: Services, Complaints" or detect "all selected" client-side.
Instead add a second, single-row query to `queries[]` that pre-formats the whole line server-side
using `CASE`/`STRING_AGG`, and point `filtersSummaryExpression` at it with `Max(...)` (safe for a
single-row result, and works on strings):

```jsonc
{
  "filtersSummaryExpression": "Max([FiltersSummary.SummaryText])",
  "queries": [
    { "name": "CasesData", "sql": "SELECT ... FROM SM_Cases WHERE (@categories IS NULL OR ...) ...", "columns": [ ... ] },
    { "name": "FiltersSummary", "sql":
      "SELECT 'Category: ' + CASE WHEN @categories IS NULL THEN 'All' WHEN (SELECT COUNT(*) FROM string_split(@categories,',')) >= 2 THEN 'All' ELSE (SELECT STRING_AGG(CASE Value WHEN '1' THEN 'Services' WHEN '2' THEN 'Complaints' END, ', ') FROM string_split(@categories,',')) END AS SummaryText",
      "columns": [ { "field": "SummaryText", "caption": "Summary", "type": "System.String" } ] }
  ]
}
```

The `>= <total active items>` check is what makes "select all" collapse to "All" instead of listing
every option — get the real total from the live reference list / entity count (see
[data-model.md](data-model.md#discovering-valid-values)), don't guess it. Every query in
`queries[]` receives all of `spec.parameters` automatically (see the multi-query note above), so
`@categories` etc. are already in scope in `FiltersSummary`'s SQL — no extra wiring needed.

## Pivot / Dashboard

Both reuse the same envelope + Base64 data source; only the detail band differs.

- **Pivot**: an `XRPivotGrid` (`DataSource="#Ref-0" DataMember="{queryName}"`) with `<Fields>` in
  `RowArea` / `ColumnArea` / `DataArea` (`SummaryType` = `Sum|Count|Average|Min|Max`).
- **Dashboard**: KPI `XRLabel`s (expression `Sum([{queryName}.{field}])`) in the report header plus
  an `XRChart` (bar graph via `viewType:"SideBySideBarSeriesView"`, the default). Each
  `dashboard.series` entry is one of:
  - **value series** — `{ "caption","valueField" }`: plots a pre-aggregated numeric column
    (`ValueDataMembersSerializable="{queryName}.{valueField}"`). Use for "A vs B" grouped bars where
    the SQL already returns the counts per row (e.g. `Period, CasesLogged, CasesResolved`).
  - **count series** — `{ "caption","summary" }` (no `valueField`): counts rows per argument value
    (`QualitativeSummaryOptions SummaryFunction`, default `COUNT()`).
  `dashboard.argument` is the category axis column; `viewType` can be any DX series view
  (`SideBySideBarSeriesView`, `StackedBarSeriesView`, `LineSeriesView`, `PieSeriesView`, …).
  For **several charts** (and charts from different queries) use `dashboard.charts[]` + `queries[]`
  (see the spec.json example above). Pie/doughnut charts omit the XY diagram automatically; bar/line
  charts get an `XYDiagram` with X/Y axes.

## Type name reference

| Spec `type` (.NET) | ResultSchema type | Use for |
|--------------------|-------------------|---------|
| `System.String`   | String   | text, GUID-as-string, reference-list labels |
| `System.Guid`     | Guid     | entity keys |
| `System.Int32`    | Int32    | whole numbers |
| `System.Int64`    | Int64    | reference-list item values |
| `System.Decimal`  | Decimal  | money/amounts |
| `System.Double`   | Double   | floats |
| `System.DateTime` | DateTime | dates |
| `System.Boolean`  | Boolean  | yes/no |

Root assembly suffix: `, DevExpress.XtraReports.v23.1, Version=23.1.5.0, Culture=neutral, PublicKeyToken=b88d1754d700e49a`.
SqlDataSource `ObjectType` uses the short form `DevExpress.DataAccess.Sql.SqlDataSource,DevExpress.DataAccess.v23.1` (no version/token).

## Troubleshooting

**Don't diagnose XML/layout problems by guessing — use the DXXRDV render check**
([api-access.md](api-access.md#verify)) to get an authoritative success/failure signal from the
actual report engine before changing anything below.

- **Viewer errors loading the layout** → this is *not* necessarily a `SerializerVersion` mismatch:
  confirmed live that a layout serialized as `23.1.5.0` loads fine under a site whose web viewer
  reports `"reporting":"23.2.13"` in its `dxversions` — the layout serializer version and the
  installed web-viewer/analytics version are independent numbers, and DevExpress's serializer is
  backward-compatible across 23.x. Don't "fix" `SerializerVersion`/`Version=`/the `v23.1` assembly
  tokens in `build-report-xml.js` just because `dxversions` shows a newer number — verify with
  DXXRDV first; only change these if that check actually shows a load failure tied to the version.
- **Columns blank** → a detail-cell `Expression="[{view}.{field}]"` doesn't match a `ResultSchema`
  field / SELECT alias. Alias every column; keep `queryName` consistent everywhere.
- **Filters do nothing** → parameter `Name` / `internalName` / form `propertyName` / SQL `@param`
  mismatch. See [data-model.md](data-model.md#how-a-filter-reaches-the-sql).
- **Filter picker shows raw ids/guids instead of names, or the wrong record gets selected** → this
  is an `entityDisplayProperty`/value-shape bug, not an XML bug — see
  [filter-form.md](filter-form.md#verify-entitydisplayproperty-before-trusting-it).
- **A column/KPI shows the wrong currency symbol (or the right symbol on one host and the wrong one
  on another)** → don't use `.NET`'s generic currency specifier (`{0:C}` / `{0:C2}`) for a `format`
  that must show a *specific* symbol regardless of deployment. `C` resolves against the **server's**
  ambient culture at render time, not the caller's locale or anything in the spec — the exact same
  report definition rendered `$` on one host and needs an explicit symbol to be portable. Use a
  literal prefix instead, e.g. `"R{0:N2}"` for Rand, `"€{0:N2}"` for Euro — `N2` formats the number
  (with the server's thousands/decimal separator convention, which is a much smaller cosmetic
  difference than the symbol being wrong) and the literal character is never culture-substituted.
  This applies to both table-column `format` and `kpis[].format`.
- **`/DXXRDV` fails identically for every report on one specific deployment**, with an **empty
  response body and no ABP JSON envelope at all** (every other endpoint — auth, `ReportingReport/Get`,
  etc. — always wraps errors as `{success:false, error:{...}}`; only this one returns nothing) → this
  is not a report/data/connection-string problem. It's the signature of a dependency-injection
  failure resolving the WebDocumentViewer controller itself, confirmed via one real deployment's
  `/elmah/errors` page (if ElmahCore is installed — check there first, it names the exact exception
  in one shot): `Castle.MicroKernel.ComponentNotFoundException: No component for supporting the
  service ...CustomWebDocumentViewerController was found`. The fix in that case was a missing
  `services.RegisterReportingControllers()` call (from `boxfusion.devexpressreporting.Common.Extensions`)
  in the host's `Startup.cs`/`ConfigureServices` — this registration is **not automatic** just because
  the module is referenced. To confirm it's deployment-wide and not something about the one report
  you're debugging: deploy a second, structurally unrelated report to the same host and check whether
  it fails with the *exact same* empty-500 signature — if both do, stop debugging the report content
  and go looking at the host's DI/startup wiring instead.
- **Last-resort repair** → open the report once in the DevExpress designer and save; it rewrites the
  layout in the exact serialization the install expects.
