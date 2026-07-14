---
name: create-devexpress-report
description: Auto-creates DevExpress reports in a Shesha application from natural-language requirements — instead of hand-configuring them in the front-end report designer. Generates the DevExpress XtraReport definition XML (SQL data source + bands/tables), the report parameters, and a Shesha filter form, then deploys them live to a target site via its API. Calls the generate-sql-query skill for the report SQL and builds the filter form itself. Use when the user asks to "create a report", "auto-generate a report", "build a DevExpress report", "add a report", "scaffold a reporting report", or configure a report without using the designer UI, for the pd-devexpressreporting / DevExpressReporting module.
---

# Create DevExpress Report

Automate creation of a DevExpress report in a Shesha app that uses the **DevExpressReporting**
module (`boxfusion.devexpressreporting`), so the user does **not** have to configure it manually
in the front-end report designer.

A report is a `ReportingReport` row whose core is `ReportDefinitionXml` — a DevExpress
**XtraReport layout XML (serializer v23.1.5)** that embeds a `SqlDataSource` (connection + SQL)
and the bands/tables that render the columns. Filters are a Shesha `ConfigurableForm` referenced
by the report's `ParameterFormPath`. This skill builds all three artifacts and pushes them live.

Read the bundled references as you reach each step — do not preload them all.

## Prerequisites

**HARD GATE — always prompt, never assume.** Before doing anything else, obtain these from the
user **in the current request**:

- **Target site base URL** — the running Shesha site to configure (e.g. `https://myapp.boxfusion.co.za`).
- **Admin credentials** — `username` + `password` (a user in `app:Configurator` / SysAdmin).

If the base URL, username, or password is **not explicitly provided in the current request, STOP and
ask for it.** Never fill these in from: an earlier message or a previous report in this conversation,
a prior run, memory, an environment/config file, an example in these docs, or any default. There is
no default site and no default login — a wrong target could write a report to the wrong system.
Re-prompt on every run unless the user has, in this same request, told you which site + credentials
to use. (The `deploy-report.js` and `discover-metadata.js` scripts also refuse to run without these
passed as arguments — but the rule above is on you, not just the scripts.)

Also gather (ask only if not inferable):

- **MSSQL connection** — `mssql_server`, `mssql_database` (+ optional user/password). Needed by
  generate-sql-query to validate the SQL, and to confirm result columns. (Optional if the report
  resolves its connection server-side via the named `Default` connection.)
- **Report requirement** — the natural-language description of what the report should show and
  which filters the end user needs.

`Node.js` must be available (`node --version`) — the bundled scripts run under it. No npm install is
required; the scripts use only Node's built-in `https`/`http` and `crypto`.

## Pipeline

### Step 1 — Clarify the report spec

From the requirement, settle these before generating anything (ask only what you can't infer):

- **Report type** — `Report` (tabular list, the default), `Pivot` (cross-tab), or `Dashboard`
  (chart-oriented). See [reference/report-xml.md](reference/report-xml.md) for what each supports.
- **Title / display name**, **description**, **menu category**, **connection string name**
  (usually `Default`), whether it **shows in the reports menu**.
- **Filters** — for each: label, the SQL column it filters, and its data type (text, number,
  date, datetime, boolean, reference-list, entity reference). These become both report parameters
  and filter-form fields.

**Never hardcode project-specific names.** Reference-list names/modules, entity types, FK columns,
category values, and reflist item values are all **resolved from the target site's APIs** before
building. Use the bundled discovery script:

```bash
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' entity <ClassName>   # table, FK columns, reflist props
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' reflist <name>       # full reflist name/module + item values
node <skill-dir>/scripts/discover-metadata.js <baseUrl> <user> '<pass>' category             # valid report categories
```

See [reference/data-model.md](reference/data-model.md#discovering-valid-values) for details. Resolve
every reflist/entity filter, the agent/lookup columns, and `Category`/`ConnectionStringName` this way.
If a reflist has **several matches with differing item values**, either pick the one for the exact
column or resolve labels in SQL via `dbo.Frwk_GetRefListItem('<module>','<ShortName>', <col>)`. If a
value can't be resolved on the target site, stop and ask — do not guess.

### Step 2 — Generate the SQL

Invoke the **generate-sql-query** skill with the report requirement to produce the read-only
SELECT. Then adapt it for filtering: for every filter from Step 1, add a `@paramName` predicate
to the `WHERE` clause using the `NULL`-guarded pattern so unset filters are ignored:
- scalar: `AND (@startDate IS NULL OR o.CreationTime >= @startDate)`
- multi-value: `AND (@statuses IS NULL OR o.StatusLkp IN (SELECT Value FROM string_split(@statuses,',')))`

Keep `@paramName` identical to the parameter `internalName` used in Steps 3–5. **Alias every SELECT
column** (the alias becomes the bound field name). Record the final column list (name + .NET type)
— it drives both the table columns and the data source `ResultSchema`.

Build the `connectionString` for the spec from the MSSQL inputs
(`Data Source={server};Initial Catalog={database};User={user};Password={pw};MultipleActiveResultSets=True;TrustServerCertificate=True`);
the build script appends `;XpoProvider=MSSqlServer`.

### Step 3 — Build the report definition XML

Run the build script with the report meta, SQL, columns, and parameters. It emits the
`ReportDefinitionXml` and does **not** touch the network:

```bash
node <skill-dir>/scripts/build-report-xml.js <spec.json> > report.xml
```

`spec.json` shape and the XML format are documented in
[reference/report-xml.md](reference/report-xml.md). The script constructs the bands/table for
`Report`, the pivot grid for `Pivot`, and the chart+summary layout for `Dashboard`, wires the
`SqlDataSource` to the named connection, declares the report parameters, and binds query
parameters to them.

**Styling**: every report is styled with a polished, brand-neutral look **by default** (report
header with title/logo/generated-date/accent line, colored table headers, banded KPI cards, themed
chart palette, page footer). To **follow a supplied design**, pass a `theme` object in the spec
(colors, font, title size, `logoBase64`, `footerText`, `chartPalette`) — see
[reference/report-xml.md](reference/report-xml.md#styling-theme). If the user gives brand colors or
a logo, map them into `theme`; otherwise omit it and the defaults apply.

### Step 4 — Build the filter form markup

If there are filters, generate the Shesha `ConfigurableForm` markup — one input per parameter,
each input's `propertyName` **exactly matching** the parameter `internalName`. Follow
[reference/filter-form.md](reference/filter-form.md) for the component per data type and the
overall markup shape. The build script can emit this too (`--form` mode) or you can assemble it
inline. Skip this step only if the report has no filters.

### Step 5 — Deploy live to the target site

Run the deploy script. It authenticates, then creates the artifacts in the correct order
(form → report → parameters) and links them:

```bash
node <skill-dir>/scripts/deploy-report.js <baseUrl> <username> '<password>' <deploy.json> [--dry-run]
```

Always run `--dry-run` first and show the user the planned payloads. Endpoint paths, payload
shapes, and the create order are in [reference/api-access.md](reference/api-access.md). After the
real run, capture the returned report `id`.

### Step 6 — Verify

Confirm the report loads:
- Fetch it back: `GET {baseUrl}/api/services/DevExpressReporting/ReportingReport/Get?id=<id>`.
- Open the report viewer for that id and confirm it renders and the filter form appears.
- If the viewer errors on the layout, the XML failed to load — see
  [reference/report-xml.md](reference/report-xml.md#troubleshooting). As a last-resort repair, open
  the report once in the DevExpress designer (it re-serializes the layout), then re-run parameters.

Report back: the report id, its menu location, the filter form id, and the verification result.
Never claim success without the Step-6 fetch/render check.

## Report-type support

| Type | Value | What the script generates | Notes |
|------|-------|---------------------------|-------|
| Report | 1 | Title band + column-header band + detail `XRTable` bound to SELECT columns | Full support |
| Pivot | 2 | `XRPivotGrid` with row/column/data fields from the spec | Set `pivot` fields in spec |
| Dashboard | 3 | Summary labels + `XRChart` (series bound to columns) | Chart-style report; simpler than a native DX dashboard |

## Bundled resources

- [reference/data-model.md](reference/data-model.md) — `ReportingReport` / `ReportingReportParameter` fields, reference lists, and how to discover valid Category / ConnectionString values.
- [reference/report-xml.md](reference/report-xml.md) — DevExpress v23.1 XtraReport XML anatomy for all three types, `spec.json` shape, parameter binding, troubleshooting.
- [reference/filter-form.md](reference/filter-form.md) — Shesha `ConfigurableForm` markup per data type; propertyName alignment rules.
- [reference/form-components.md](reference/form-components.md) — catalog of all supported form components and their property shapes (from a survey of real Shesha forms); how to emit any component via `component` / `componentProps`.
- [reference/api-access.md](reference/api-access.md) — authentication + create endpoints, payloads, and deploy order.
- `scripts/discover-metadata.js` — resolves entities/tables/FK columns, reference-list names+modules+items, and report categories from the target site (so nothing is hardcoded).
- `scripts/build-report-xml.js` — builds `ReportDefinitionXml` (and optionally the form markup) offline.
- `scripts/deploy-report.js` — authenticates and creates form + report + parameters via the API.
