#!/usr/bin/env node
/**
 * Build a DevExpress XtraReport definition XML (serializer v23.1.5) from a spec.
 * The format is reverse-engineered from real reports saved by the v23.1 designer
 * (see reference/report-xml.md). The SqlDataSource is emitted as a Base64-encoded
 * inner XML blob inside <ComponentStorage> exactly as the designer produces it.
 *
 * Usage:
 *   node build-report-xml.js <spec.json>            # prints ReportDefinitionXml to stdout
 *   node build-report-xml.js --form <spec.json>     # prints Shesha filter-form markup (JSON) to stdout
 *
 * No network access; only reads the spec file and writes to stdout.
 */

const fs = require('fs');
const crypto = require('crypto');

const DX = {
  serializer: '23.1.5.0',
  version: '23.1',
  xtraReport: 'DevExpress.XtraReports.UI.XtraReport, DevExpress.XtraReports.v23.1, Version=23.1.5.0, Culture=neutral, PublicKeyToken=b88d1754d700e49a',
  sqlDataSource: 'DevExpress.DataAccess.Sql.SqlDataSource,DevExpress.DataAccess.v23.1',
  objectStorageInfo: 'DevExpress.XtraReports.Serialization.ObjectStorageInfo, DevExpress.XtraReports.v23.1',
};

// .NET type -> short ResultSchema field type
const SCHEMA_TYPE = {
  'System.String': 'String', 'System.Guid': 'Guid', 'System.DateTime': 'DateTime',
  'System.Int16': 'Int16', 'System.Int32': 'Int32', 'System.Int64': 'Int64',
  'System.Decimal': 'Decimal', 'System.Double': 'Double', 'System.Boolean': 'Boolean',
  'System.Byte': 'Byte', 'System.TimeSpan': 'TimeSpan',
};

function xmlEscape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let refCounter = 2; // 0 = data source, 1 = report root
const nextRef = () => refCounter++;

// ── SqlDataSource inner XML (later Base64-encoded) ──────────────────────────

function connectionXml(spec) {
  const name = xmlEscape(spec.connectionStringName || 'Default');
  if (spec.connectionString) {
    let cs = spec.connectionString;
    if (!/XpoProvider=/i.test(cs)) cs += ';XpoProvider=MSSqlServer';
    return `<Connection Name="${name}" ConnectionString="${xmlEscape(cs)}" />`;
  }
  // No explicit string: resolve server-side via ConnectionStringsProvider / app config by name.
  return `<Connection Name="${name}" FromAppConfig="true" />`;
}

function queryParametersXml(params) {
  return (params || []).map((p) =>
    `<Parameter Name="${xmlEscape(p.name)}" Type="DevExpress.DataAccess.Expression">` +
    `(${p.type || 'System.String'})(?${xmlEscape(p.name)})</Parameter>`
  ).join('');
}

// A report can have one query (spec.sql/queryName/columns) or several (spec.queries[]).
// Each query = { name, sql, columns:[{field,type}] } and becomes a <Query> + a ResultSchema <View>.
function queriesOf(spec) {
  if (Array.isArray(spec.queries) && spec.queries.length) {
    return spec.queries.map((q) => ({ name: q.name, sql: q.sql, columns: q.columns || [] }));
  }
  return [{ name: spec.queryName || 'Query', sql: spec.sql, columns: spec.columns || [] }];
}

function sqlDataSourceBase64(spec) {
  const dsName = spec.dataSourceName || 'ReportData';
  const queries = queriesOf(spec);
  // Every query declares all report parameters, so @params bind in each query's SQL.
  const queriesXml = queries.map((q) =>
    `<Query Type="CustomSqlQuery" Name="${xmlEscape(q.name)}">` +
    queryParametersXml(spec.parameters) +
    `<Sql>${xmlEscape(q.sql)}</Sql>` +
    `</Query>`
  ).join('');
  const views = queries.map((q) => {
    const fields = (q.columns || []).map((c) =>
      `<Field Name="${xmlEscape(c.field)}" Type="${SCHEMA_TYPE[c.type] || 'String'}" />`).join('');
    return `<View Name="${xmlEscape(q.name)}">${fields}</View>`;
  }).join('');
  const inner =
    `<SqlDataSource Name="${xmlEscape(dsName)}">` +
    connectionXml(spec) +
    queriesXml +
    `<ResultSchema><DataSet Name="${xmlEscape(dsName)}">${views}</DataSet></ResultSchema>` +
    `<ConnectionOptions CloseConnection="true" />` +
    `</SqlDataSource>`;
  return Buffer.from(inner, 'utf8').toString('base64');
}

// ── report-level parameters + ObjectStorage type table ──────────────────────

function buildParametersAndStorage(spec) {
  const params = spec.parameters || [];
  const typeRefs = {};           // netType -> Ref in ObjectStorage (scalar params only)
  const storageItems = [];

  // Allocate a shared ObjectStorage entry per distinct scalar type.
  for (const p of params) {
    if (p.multiValue) continue;
    const t = p.type || 'System.String';
    if (!typeRefs[t]) {
      const r = nextRef();
      typeRefs[t] = r;
      storageItems.push(
        `    <Item${storageItems.length + 1} ObjectType="${DX.objectStorageInfo}" Ref="${r}" Content="${t}" Type="System.Type" />`);
    }
  }

  const paramItems = [];
  const paramRefs = [];
  params.forEach((p, i) => {
    const ref = nextRef();
    paramRefs.push(ref);
    const desc = xmlEscape(p.displayName || p.name);
    if (p.multiValue) {
      paramItems.push(
        `    <Item${i + 1} Ref="${ref}" Description="${desc}" AllowNull="true" MultiValue="true" Name="${xmlEscape(p.name)}" />`);
    } else {
      const valueInfo = p.default != null ? ` ValueInfo="${xmlEscape(p.default)}"` : '';
      paramItems.push(
        `    <Item${i + 1} Ref="${ref}" Description="${desc}"${valueInfo} Name="${xmlEscape(p.name)}" Type="#Ref-${typeRefs[p.type || 'System.String']}" />`);
    }
  });

  const parametersXml = paramItems.length
    ? `  <Parameters>\n${paramItems.join('\n')}\n  </Parameters>\n` : '';
  const objectStorageXml = storageItems.length
    ? `  <ObjectStorage>\n${storageItems.join('\n')}\n  </ObjectStorage>\n` : '';

  const panelItems = paramRefs.map((r, i) =>
    `    <Item${i + 1} Ref="${nextRef()}" LayoutItemType="Parameter" Parameter="#Ref-${r}" />`);
  const panelXml = panelItems.length
    ? `  <ParameterPanelLayoutItems>\n${panelItems.join('\n')}\n  </ParameterPanelLayoutItems>\n` : '';

  return { parametersXml, objectStorageXml, panelXml };
}

// ── bands ────────────────────────────────────────────────────────────────────

// ── theme ────────────────────────────────────────────────────────────────────

function hexToArgb(hex) {
  let h = String(hex).replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `255,${r},${g},${b}`;
}
// Normalise a colour to DevExpress "a,r,g,b". Accepts #RRGGBB, "r,g,b", "a,r,g,b", or a named colour.
function argb(c) {
  if (!c) return c;
  if (String(c)[0] === '#') return hexToArgb(c);
  const parts = String(c).split(',');
  if (parts.length === 3) return `255,${c}`;
  return c;
}

// Resolve the report theme: professional defaults, fully overridable via spec.theme so a supplied
// design can be followed. All colours normalised to "a,r,g,b".
function resolveTheme(spec) {
  const t = spec.theme || {};
  return {
    // Default to Arial: it renders on Windows AND on Linux/Skia report servers. Fonts like
    // "Segoe UI" are Windows-only and throw ArgumentException at document build on Linux hosts.
    font: t.fontFamily || 'Arial',
    primary: argb(t.primaryColor || '#2E4A62'),
    accent: argb(t.accentColor || '#E8863C'),
    headerText: argb(t.headerTextColor || '#FFFFFF'),
    band: argb(t.bandColor || '#EEF2F6'),
    text: argb(t.textColor || '#333333'),
    grid: argb(t.gridColor || '#D9DEE4'),
    titleSize: t.titleSize || 16,
    logoBase64: t.logoBase64 || null,
    footerText: t.footerText || t.organizationName || '',
    chartPalette: t.chartPalette || 'Nature Colors',
  };
}

// Content width = page width minus the 50+50 margins.
function contentWidth(spec) { return (spec.pageWidth || (spec.landscape ? 1100 : 850)) - 100; }

// Shared, styled ReportHeader controls: optional logo, title, description, generated-on, accent line.
function headerControls(theme, spec, pageW) {
  const items = [];
  let n = 0; const next = () => ++n;
  if (theme.logoBase64) {
    items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRPictureBox" Name="logo" ImageSource="img,${theme.logoBase64}" Sizing="ZoomImage" SizeF="150,45" LocationFloat="${pageW - 150},0" />`);
  }
  items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRLabel" Name="lblTitle" Text="${xmlEscape(spec.title || spec.reportName)}" SizeF="${pageW - 160},30" LocationFloat="0,4" Font="${theme.font}, ${theme.titleSize}pt, style=Bold" ForeColor="${theme.primary}" Padding="2,2,0,0,100" />`);
  if (spec.description) {
    items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRLabel" Name="lblSubtitle" Text="${xmlEscape(spec.description)}" SizeF="${pageW - 160},18" LocationFloat="0,36" Font="${theme.font}, 9pt" ForeColor="${theme.text}" Padding="2,2,0,0,100" />`);
  }
  items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRPageInfo" Name="genDate" PageInfo="DateTime" TextFormatString="Generated: {0:dd MMM yyyy HH:mm}" TextAlignment="MiddleRight" SizeF="240,16" LocationFloat="${pageW - 240},58" Font="${theme.font}, 8pt" ForeColor="${theme.text}" />`);
  items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRLine" Name="accentLine" LineWidth="2" SizeF="${pageW},4" LocationFloat="0,78" ForeColor="${theme.accent}" />`);
  return items.join('\n');
}

// Shared, styled BottomMargin controls: accent line, footer text, page numbers.
function footerControls(theme, pageW) {
  const items = [];
  let n = 0; const next = () => ++n;
  items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRLine" Name="footLine" LineWidth="1" SizeF="${pageW},2" LocationFloat="0,4" ForeColor="${theme.accent}" />`);
  if (theme.footerText) {
    items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRLabel" Name="footText" Text="${xmlEscape(theme.footerText)}" SizeF="${pageW - 160},16" LocationFloat="0,10" Font="${theme.font}, 8pt" ForeColor="${theme.text}" Padding="2,2,0,0,100" />`);
  }
  items.push(`        <Item${next()} Ref="${nextRef()}" ControlType="XRPageInfo" Name="pageInfo" PageInfo="NumberOfTotal" TextFormatString="Page {0} of {1}" TextAlignment="MiddleRight" SizeF="150,16" LocationFloat="${pageW - 150},10" Font="${theme.font}, 8pt" ForeColor="${theme.text}" />`);
  return items.join('\n');
}

// ── bands ────────────────────────────────────────────────────────────────────

function tabularBands(spec) {
  const theme = resolveTheme(spec);
  const cols = spec.columns || [];
  const totalW = contentWidth(spec);
  const weight = cols.length ? +(totalW / cols.length).toFixed(2) : totalW;
  const view = spec.queryName || 'Query';

  const headerCells = cols.map((c, i) =>
    `                <Item${i + 1} Ref="${nextRef()}" ControlType="XRTableCell" Name="hc_${xmlEscape(c.field)}" Weight="${weight}" Text="${xmlEscape(c.caption || c.field)}" Font="${theme.font}, 9.75pt, style=Bold" ForeColor="${theme.headerText}" BackColor="${theme.primary}" Padding="6,6,4,4,100" TextAlignment="MiddleLeft" />`
  ).join('\n');

  const detailCells = cols.map((c, i) => {
    const fmt = c.format ? ` TextFormatString="${xmlEscape(c.format)}"` : '';
    const align = /Int|Decimal|Double|Single/.test(c.type || '') ? 'MiddleRight' : 'MiddleLeft';
    return `                <Item${i + 1} Ref="${nextRef()}" ControlType="XRTableCell" Name="dc_${xmlEscape(c.field)}" Weight="${weight}"${fmt} Font="${theme.font}, 9pt" ForeColor="${theme.text}" Borders="Bottom" BorderColor="${theme.grid}" Padding="6,6,4,4,100" TextAlignment="${align}">\n` +
      `                  <ExpressionBindings>\n` +
      `                    <Item1 Ref="${nextRef()}" EventName="BeforePrint" PropertyName="Text" Expression="[${xmlEscape(view)}.${xmlEscape(c.field)}]" />\n` +
      `                  </ExpressionBindings>\n` +
      `                </Item${i + 1}>`;
  }).join('\n');

  const header = headerControls(theme, spec, totalW);
  const phTableRef = nextRef(), phRowRef = nextRef();
  const dTableRef = nextRef(), dRowRef = nextRef();

  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="45" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="90">
      <Controls>
${header}
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="PageHeaderBand" Name="PageHeader" HeightF="28">
      <Controls>
        <Item1 Ref="${phTableRef}" ControlType="XRTable" Name="tblHeader" SizeF="${totalW},28" LocationFloat="0,0">
          <Rows>
            <Item1 Ref="${phRowRef}" ControlType="XRTableRow" Name="tblHeaderRow" Weight="1">
              <Cells>
${headerCells}
              </Cells>
            </Item1>
          </Rows>
        </Item1>
      </Controls>
    </Item3>
    <Item4 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="24">
      <Controls>
        <Item1 Ref="${dTableRef}" ControlType="XRTable" Name="tblDetail" SizeF="${totalW},24" LocationFloat="0,0">
          <Rows>
            <Item1 Ref="${dRowRef}" ControlType="XRTableRow" Name="tblDetailRow" Weight="1">
              <Cells>
${detailCells}
              </Cells>
            </Item1>
          </Rows>
        </Item1>
      </Controls>
    </Item4>
    <Item5 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="40">
      <Controls>
${footerControls(theme, totalW)}
      </Controls>
    </Item5>
  </Bands>`;
}

function pivotBands(spec) {
  const theme = resolveTheme(spec);
  const p = spec.pivot || { rows: [], columns: [], data: [] };
  const view = spec.queryName || 'Query';
  const totalW = contentWidth(spec);
  const fields = [];
  let idx = 1;
  (p.rows || []).forEach((f, i) => fields.push(
    `            <Item${idx++} Ref="${nextRef()}" FieldName="${xmlEscape(f)}" Area="RowArea" AreaIndex="${i}" Caption="${xmlEscape(f)}" />`));
  (p.columns || []).forEach((f, i) => fields.push(
    `            <Item${idx++} Ref="${nextRef()}" FieldName="${xmlEscape(f)}" Area="ColumnArea" AreaIndex="${i}" Caption="${xmlEscape(f)}" />`));
  (p.data || []).forEach((d, i) => {
    const fmt = d.format ? ` CellFormat="${xmlEscape(d.format)}"` : '';
    fields.push(
      `            <Item${idx++} Ref="${nextRef()}" FieldName="${xmlEscape(d.field)}" Area="DataArea" AreaIndex="${i}" Caption="${xmlEscape(d.caption || d.field)}" SummaryType="${d.summary || 'Sum'}"${fmt} />`);
  });
  const header = headerControls(theme, spec, totalW);
  const pivotRef = nextRef();
  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="45" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="90">
      <Controls>
${header}
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="400">
      <Controls>
        <Item1 Ref="${pivotRef}" ControlType="XRPivotGrid" Name="pivotGrid1" DataSource="#Ref-0" DataMember="${xmlEscape(view)}" SizeF="${totalW},400" LocationFloat="0,0" Font="${theme.font}, 9pt">
          <Fields>
${fields.join('\n')}
          </Fields>
        </Item1>
      </Controls>
    </Item3>
    <Item4 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="40">
      <Controls>
${footerControls(theme, totalW)}
      </Controls>
    </Item4>
  </Bands>`;
}

// chartType → DevExpress series view + whether it uses an XY (axis) diagram.
const CHART_VIEW = {
  bar: { view: 'SideBySideBarSeriesView', xy: true },
  stackedbar: { view: 'StackedBarSeriesView', xy: true },
  line: { view: 'LineSeriesView', xy: true },
  area: { view: 'AreaSeriesView', xy: true },
  pie: { view: 'PieSeriesView', xy: false },
  doughnut: { view: 'DoughnutSeriesView', xy: false },
};
function resolveChartView(ch) {
  if (ch.viewType) return { view: ch.viewType, xy: !/Pie|Doughnut|Funnel/i.test(ch.viewType) };
  return CHART_VIEW[(ch.chartType || 'bar').toLowerCase()] || CHART_VIEW.bar;
}

// One XRChart control (as Item{idx}) bound to chart.dataMember. value series (valueField) plot a
// pre-aggregated column; count series COUNT() rows. Pie/doughnut omit the XY diagram.
function chartControl(theme, ch, idx, x, y, w, h) {
  const dm = ch.dataMember;
  const cv = resolveChartView(ch);
  const seriesXml = (ch.series || []).map((s, i) => {
    const sRef = nextRef(), vRef = nextRef();
    const arg = `ArgumentDataMember="${xmlEscape(dm)}.${xmlEscape(ch.argument)}"`;
    const name = xmlEscape(s.caption || s.valueField || s.field || `Series${i + 1}`);
    if (s.valueField) {
      return `                <Item${i + 1} Ref="${sRef}" DataSource="#Ref-0" Name="${name}" SeriesID="${i}" ${arg} ValueDataMembersSerializable="${xmlEscape(dm)}.${xmlEscape(s.valueField)}" ArgumentScaleType="Qualitative" ValueScaleType="Numerical">\n` +
        `                  <View Ref="${vRef}" TypeNameSerializable="${cv.view}" />\n` +
        `                </Item${i + 1}>`;
    }
    const qRef = nextRef();
    return `                <Item${i + 1} Ref="${sRef}" DataSource="#Ref-0" Name="${name}" SeriesID="${i}" ${arg} ArgumentScaleType="Qualitative">\n` +
      `                  <View Ref="${vRef}" ColorEach="true" TypeNameSerializable="${cv.view}" />\n` +
      `                  <QualitativeSummaryOptions Ref="${qRef}" SummaryFunction="${s.summary || 'COUNT()'}" />\n` +
      `                </Item${i + 1}>`;
  }).join('\n');
  const chRef = nextRef(), chRef2 = nextRef(), dcRef = nextRef(), legRef = nextRef();
  const diagram = cv.xy
    ? `            <Diagram Ref="${nextRef()}" TypeNameSerializable="XYDiagram">\n              <AxisX Ref="${nextRef()}" VisibleInPanesSerializable="-1" />\n              <AxisY Ref="${nextRef()}" VisibleInPanesSerializable="-1" />\n            </Diagram>\n`
    : '';
  return `        <Item${idx} Ref="${chRef}" ControlType="XRChart" Name="chart${idx}" DataSource="#Ref-0" SizeF="${w},${h}" LocationFloat="${x},${y}" Borders="None">
          <Chart Ref="${chRef2}" PaletteName="${xmlEscape(theme.chartPalette)}">
            <DataContainer Ref="${dcRef}" DataMember="${xmlEscape(dm)}" ValidateDataMembers="true">
              <SeriesSerializable>
${seriesXml}
              </SeriesSerializable>
            </DataContainer>
${diagram}            <Legend Ref="${legRef}" LegendID="-1" />
          </Chart>
        </Item${idx}>`;
}

function dashboardBands(spec) {
  const theme = resolveTheme(spec);
  const d = spec.dashboard || {};
  const primary = queriesOf(spec)[0].name;
  const totalW = contentWidth(spec);

  // Charts: use d.charts[] when present; otherwise wrap the legacy single-chart config.
  const charts = (d.charts && d.charts.length)
    ? d.charts.map((c) => ({ ...c, dataMember: c.dataMember || primary }))
    : [{ dataMember: primary, viewType: d.viewType || 'SideBySideBarSeriesView', argument: d.argument, series: d.series || [] }];

  let ci = 0; const nextCi = () => ++ci;
  const controls = [];

  // KPI cards across the top.
  const kpis = d.kpis || [];
  kpis.forEach((k, i) => {
    const fmt = k.format ? ` TextFormatString="${xmlEscape(k.format)}"` : '';
    const x = i * (230 + 12);
    const dm = k.dataMember || primary;
    controls.push(
      `        <Item${nextCi()} Ref="${nextRef()}" ControlType="XRLabel" Name="kpi_${xmlEscape(k.field)}" SizeF="230,48" LocationFloat="${x},0" BackColor="${theme.band}" ForeColor="${theme.primary}" Font="${theme.font}, 12pt, style=Bold" Padding="10,10,6,6,100" TextAlignment="MiddleLeft"${fmt}>\n` +
      `          <ExpressionBindings>\n` +
      `            <Item1 Ref="${nextRef()}" EventName="BeforePrint" PropertyName="Text" Expression="'${xmlEscape(k.caption || k.field)}: ' + ${k.summary || 'Sum'}([${xmlEscape(dm)}.${xmlEscape(k.field)}])" />\n` +
      `          </ExpressionBindings>\n` +
      `        </Item${ci}>`);
  });

  // Charts stacked vertically below the KPIs.
  let y = kpis.length ? 60 : 0;
  charts.forEach((ch) => {
    if (ch.title) {
      controls.push(`        <Item${nextCi()} Ref="${nextRef()}" ControlType="XRLabel" Name="chartTitle${ci}" Text="${xmlEscape(ch.title)}" SizeF="${totalW},18" LocationFloat="0,${y}" Font="${theme.font}, 11pt, style=Bold" ForeColor="${theme.primary}" Padding="2,2,0,0,100" />`);
      y += 22;
    }
    const h = ch.height || 260;
    controls.push(chartControl(theme, ch, nextCi(), 0, y, totalW, h));
    y += h + 16;
  });

  const header = headerControls(theme, spec, totalW);
  const detailH = y + 6;
  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="45" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="90">
      <Controls>
${header}
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="${detailH}">
      <Controls>
${controls.join('\n')}
      </Controls>
    </Item3>
    <Item4 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="40">
      <Controls>
${footerControls(theme, totalW)}
      </Controls>
    </Item4>
  </Bands>`;
}

// ── assemble ─────────────────────────────────────────────────────────────────

function buildReportXml(spec) {
  if (!spec.sql && !(Array.isArray(spec.queries) && spec.queries.length)) {
    throw new Error('spec.sql (or spec.queries[]) is required');
  }
  refCounter = 2;

  const { parametersXml, objectStorageXml, panelXml } = buildParametersAndStorage(spec);

  const type = (spec.type || 'Report').toLowerCase();
  let bands;
  if (type === 'pivot') bands = pivotBands(spec);
  else if (type === 'dashboard') bands = dashboardBands(spec);
  else bands = tabularBands(spec);

  const base64 = sqlDataSourceBase64(spec);
  const dsName = spec.dataSourceName || 'ReportData';
  const componentStorage =
    `  <ComponentStorage>\n` +
    `    <Item1 Ref="0" ObjectType="${DX.sqlDataSource}" Name="${xmlEscape(dsName)}" Base64="${base64}" />\n` +
    `  </ComponentStorage>`;

  const landscape = spec.landscape ? ' Landscape="true"' : '';
  const pageW = spec.pageWidth || (spec.landscape ? 1100 : 850);
  const pageH = spec.pageHeight || (spec.landscape ? 850 : 1100);
  const theme = resolveTheme(spec);
  const dataMember = xmlEscape(queriesOf(spec)[0].name);

  return `<?xml version="1.0" encoding="utf-8"?>
<XtraReportsLayoutSerializer SerializerVersion="${DX.serializer}" Ref="1" ControlType="${DX.xtraReport}" Name="${xmlEscape(spec.reportName || 'Report')}"${landscape} Margins="50, 50, 50, 50" PageWidth="${pageW}" PageHeight="${pageH}" Font="${theme.font}, 9.75pt" DataMember="${dataMember}" Version="${DX.version}" DataSource="#Ref-0">
${parametersXml}${bands}
${panelXml}${componentStorage}
${objectStorageXml}</XtraReportsLayoutSerializer>`;
}

// ── filter form markup ──────────────────────────────────────────────────────

// Full reference-list name is "<module>.<shortName>"; module stays the namespace.
function refListId(param) {
  const mod = param.referenceListNamespace || null;
  let name = param.referenceListName || null;
  if (name && mod && !name.includes('.')) name = `${mod}.${name}`;
  return { name, module: mod };
}

// Per-component-type default props, reverse-engineered from ~200 real forms in a live Shesha
// system (see reference/form-components.md). `p` is the parameter spec. These fill the
// render-critical props each component needs; callers can override via `param.componentProps`.
const COMPONENT_DEFAULTS = {
  textField: () => ({ textType: 'text', version: 5 }),
  textArea: () => ({ autoSize: false, showCount: false, allowClear: false, version: 4 }),
  numberField: () => ({ version: 4 }),
  checkbox: () => ({ version: 4 }),
  switch: () => ({ version: 3 }),
  dateField: (p) => ({
    picker: 'date', showTime: Number(p.dataType) === 4 || p.showTime === true,
    dateFormat: Number(p.dataType) === 4 ? 'DD/MM/YYYY HH:mm:ss' : 'DD/MM/YYYY',
    timeFormat: 'HH:mm:ss', defaultToMidnight: true, showNow: false,
    disabledDateMode: 'none', range: !!p.range, validate: { required: false }, version: 5,
  }),
  timeField: () => ({ version: 4 }),
  dropdown: (p) => ({
    dataSourceType: 'referenceList', useRawValues: false, referenceListId: refListId(p),
    mode: p.multiValue ? 'multiple' : 'single', valueFormat: 'simple', version: 7,
  }),
  checkboxGroup: (p) => ({
    dataSourceType: 'referenceList', direction: 'horizontal',
    mode: p.multiValue ? 'multiple' : 'single', referenceListId: refListId(p), version: 5,
  }),
  radio: (p) => ({
    dataSourceType: 'referenceList', direction: 'horizontal', referenceListId: refListId(p), version: 6,
  }),
  autocomplete: (p) => ({
    dataSourceType: 'entitiesList', useRawValues: true, entityType: p.entityTypeShortAlias || null,
    entityTypeShortAlias: p.entityTypeShortAlias || null,
    entityDisplayProperty: p.entityDisplayProperty || 'displayName',
    mode: p.multiValue ? 'multiple' : 'single', valueFormat: 'entityReference', version: 8,
  }),
  entityPicker: (p) => ({
    entityType: p.entityTypeShortAlias || null, mode: 'single', useRawValues: true,
    valueFormat: 'entityReference', version: 10,
  }),
  entityReference: (p) => ({
    entityType: p.entityTypeShortAlias || null, displayProperty: p.entityDisplayProperty || 'displayName',
    entityReferenceType: 'NavigateLink', version: 6,
  }),
  address: () => ({ version: 4 }),
  phoneNumberInput: () => ({ valueFormat: 'string', enableSearch: true, enableArrow: true, version: 0 }),
  richTextEditor: () => ({ version: 3 }),
  codeEditor: () => ({ language: 'typescript', mode: 'inline', version: 3 }),
  fileUpload: () => ({ uploadMode: 'button', allowUpload: true, allowReplace: true, allowDelete: true, version: 5 }),
  attachmentsEditor: () => ({ listType: 'text', layout: 'horizontal', version: 7 }),
  iconPicker: () => ({ version: 3 }),
  passwordCombo: () => ({ version: 6 }),
};

// GeneralDataType (parameter `type`/`dataType`) -> default component when none is specified.
const DATATYPE_COMPONENT = {
  0: 'textField', 1: 'textField', 2: 'dateField', 3: 'timeField', 4: 'dateField',
  5: 'checkbox', 6: 'numberField', 7: 'dropdown', 8: 'dropdown', 9: 'dropdown',
  10: 'autocomplete', 11: 'fileUpload', 12: 'dropdown',
};

// Build one fully-propertied component for a parameter. The component type is `param.component`
// if given (any type in COMPONENT_DEFAULTS), else derived from the data type. `param.componentProps`
// overrides/extends anything. Multi-value filters render a visible "<name>List" control whose
// onChangeCustom writes the comma-joined SQL param "<name>" so string_split(@name,',') works.
function buildComponent(param) {
  const dt = param.dataType != null ? Number(param.dataType) : 1;
  const type = param.component || DATATYPE_COMPONENT[dt] || 'textField';
  const multi = !!param.multiValue;
  const sqlName = param.name;
  const visibleName = multi ? `${sqlName}List` : sqlName;
  const base = {
    id: crypto.randomUUID(),
    type,
    propertyName: visibleName,
    componentName: visibleName,
    label: param.displayName || param.name,
    labelAlign: 'right',
    parentId: 'root',
    hidden: !!param.hideParameter,
    isDynamic: false,
    editMode: 'editable',
    validate: {},
    desktop: {}, tablet: {}, mobile: {},
  };
  const defs = (COMPONENT_DEFAULTS[type] || (() => ({})))(param);
  const comp = { ...base, ...defs, ...(param.componentProps || {}) };
  if (multi && !comp.onChangeCustom) {
    comp.onChangeCustom = `form.setFieldValue('${sqlName}', value?.join(','))`;
  }
  return comp;
}

// Back-compat alias.
function componentForType(_dataType, param) { return buildComponent(param); }

function buildFormMarkup(spec) {
  const params = spec.parameters || [];
  const components = params
    .slice()
    .sort((a, b) => (a.orderIndex || 0) - (b.orderIndex || 0))
    .map((p) => buildComponent(p));
  return {
    components,
    formSettings: {
      layout: 'horizontal',
      colon: true,
      labelCol: { span: 6 },
      wrapperCol: { span: 18 },
      version: 6,
      modelType: '',
      dataLoaderType: 'gql',
      dataSubmitterType: 'gql',
    },
  };
}

// ── main ────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  const formMode = args[0] === '--form';
  const specPath = formMode ? args[1] : args[0];
  if (!specPath) {
    console.error('Usage: node build-report-xml.js [--form] <spec.json>');
    process.exit(1);
  }
  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  if (formMode) process.stdout.write(JSON.stringify(buildFormMarkup(spec), null, 2) + '\n');
  else process.stdout.write(buildReportXml(spec) + '\n');
}

if (require.main === module) main();

module.exports = { buildReportXml, buildFormMarkup };
