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
  "dashboard": { "argument": "Region", "series": [{ "field": "Total", "summary": "COUNT()" }], "kpis": [{ "field": "Total", "caption": "Total", "summary": "Sum", "format": "{0:n2}" }] }
}
```

`columns[].type` / `parameters[].type` use .NET type names; `parameters[].dataType` is the
`GeneralDataType` value used for the filter form (see [data-model.md](data-model.md)). `multiValue`
params render as `string_split` list filters.

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
  (`SideBySideBarSeriesView`, `StackedBarSeriesView`, `LineSeriesView`, `PieSeriesView`, …). Keep it
  to one chart + KPI row; richer dashboards need the designer.

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

- **Viewer errors loading the layout** → confirm the install is DevExpress `23.1.x`; if not, change
  `SerializerVersion`, `Version=`, and the `v23.1` assembly tokens in `build-report-xml.js`.
- **Columns blank** → a detail-cell `Expression="[{view}.{field}]"` doesn't match a `ResultSchema`
  field / SELECT alias. Alias every column; keep `queryName` consistent everywhere.
- **Filters do nothing** → parameter `Name` / `internalName` / form `propertyName` / SQL `@param`
  mismatch. See [data-model.md](data-model.md#how-a-filter-reaches-the-sql).
- **Last-resort repair** → open the report once in the DevExpress designer and save; it rewrites the
  layout in the exact serialization the install expects.
