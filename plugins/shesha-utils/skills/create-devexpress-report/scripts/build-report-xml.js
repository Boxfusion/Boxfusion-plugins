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

function resultSchemaXml(spec) {
  const dsName = spec.dataSourceName || 'ReportData';
  const view = spec.queryName || 'Query';
  const fields = (spec.columns || []).map((c) =>
    `<Field Name="${xmlEscape(c.field)}" Type="${SCHEMA_TYPE[c.type] || 'String'}" />`
  ).join('');
  return `<ResultSchema><DataSet Name="${xmlEscape(dsName)}"><View Name="${xmlEscape(view)}">${fields}</View></DataSet></ResultSchema>`;
}

function sqlDataSourceBase64(spec) {
  const dsName = spec.dataSourceName || 'ReportData';
  const inner =
    `<SqlDataSource Name="${xmlEscape(dsName)}">` +
    connectionXml(spec) +
    `<Query Type="CustomSqlQuery" Name="${xmlEscape(spec.queryName || 'Query')}">` +
    queryParametersXml(spec.parameters) +
    `<Sql>${xmlEscape(spec.sql)}</Sql>` +
    `</Query>` +
    resultSchemaXml(spec) +
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

function tabularBands(spec) {
  const cols = spec.columns || [];
  const totalW = 750;
  const weight = cols.length ? +(totalW / cols.length).toFixed(2) : totalW;
  const view = spec.queryName || 'Query';

  const headerCells = cols.map((c, i) =>
    `                <Item${i + 1} Ref="${nextRef()}" ControlType="XRTableCell" Name="hc_${xmlEscape(c.field)}" Weight="${weight}" Text="${xmlEscape(c.caption || c.field)}" Font="Arial, 9.75pt, style=Bold" />`
  ).join('\n');

  const detailCells = cols.map((c, i) => {
    const fmt = c.format ? ` TextFormatString="${xmlEscape(c.format)}"` : '';
    return `                <Item${i + 1} Ref="${nextRef()}" ControlType="XRTableCell" Name="dc_${xmlEscape(c.field)}" Weight="${weight}"${fmt}>\n` +
      `                  <ExpressionBindings>\n` +
      `                    <Item1 Ref="${nextRef()}" EventName="BeforePrint" PropertyName="Text" Expression="[${xmlEscape(view)}.${xmlEscape(c.field)}]" />\n` +
      `                  </ExpressionBindings>\n` +
      `                </Item${i + 1}>`;
  }).join('\n');

  const titleRef = nextRef(), phTableRef = nextRef(), phRowRef = nextRef();
  const dTableRef = nextRef(), dRowRef = nextRef();

  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="50" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="45">
      <Controls>
        <Item1 Ref="${titleRef}" ControlType="XRLabel" Name="lblTitle" Text="${xmlEscape(spec.title || spec.reportName)}" SizeF="${totalW},30" LocationFloat="0,0" Font="Arial, 14pt, style=Bold" />
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="PageHeaderBand" Name="PageHeader" HeightF="25">
      <Controls>
        <Item1 Ref="${phTableRef}" ControlType="XRTable" Name="tblHeader" SizeF="${totalW},25" LocationFloat="0,0">
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
    <Item4 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="25">
      <Controls>
        <Item1 Ref="${dTableRef}" ControlType="XRTable" Name="tblDetail" SizeF="${totalW},25" LocationFloat="0,0">
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
    <Item5 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="50" />
  </Bands>`;
}

function pivotBands(spec) {
  const p = spec.pivot || { rows: [], columns: [], data: [] };
  const view = spec.queryName || 'Query';
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
  const titleRef = nextRef(), pivotRef = nextRef();
  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="50" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="45">
      <Controls>
        <Item1 Ref="${titleRef}" ControlType="XRLabel" Name="lblTitle" Text="${xmlEscape(spec.title || spec.reportName)}" SizeF="750,30" LocationFloat="0,0" Font="Arial, 14pt, style=Bold" />
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="400">
      <Controls>
        <Item1 Ref="${pivotRef}" ControlType="XRPivotGrid" Name="pivotGrid1" DataSource="#Ref-0" DataMember="${xmlEscape(view)}" SizeF="750,400" LocationFloat="0,0">
          <Fields>
${fields.join('\n')}
          </Fields>
        </Item1>
      </Controls>
    </Item3>
    <Item4 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="50" />
  </Bands>`;
}

function dashboardBands(spec) {
  const d = spec.dashboard || { argument: '', series: [], kpis: [] };
  const view = spec.queryName || 'Query';
  // KPI labels: Item2.. in the ReportHeader (Item1 is the title).
  const kpis = (d.kpis || []).map((k, i) => {
    const fmt = k.format ? ` TextFormatString="${xmlEscape(k.format)}"` : '';
    const x = i * 250;
    return `        <Item${i + 2} Ref="${nextRef()}" ControlType="XRLabel" Name="kpi_${xmlEscape(k.field)}" SizeF="240,40" LocationFloat="${x},40" Font="Arial, 12pt, style=Bold"${fmt}>\n` +
      `          <ExpressionBindings>\n` +
      `            <Item1 Ref="${nextRef()}" EventName="BeforePrint" PropertyName="Text" Expression="'${xmlEscape(k.caption || k.field)}: ' + ${k.summary || 'Sum'}([${xmlEscape(view)}.${xmlEscape(k.field)}])" />\n` +
      `          </ExpressionBindings>\n` +
      `        </Item${i + 2}>`;
  }).join('\n');

  const viewType = d.viewType || 'SideBySideBarSeriesView'; // bar graph by default
  // Two series modes:
  //  - value series: series has `valueField` → plots a pre-aggregated numeric column (grouped bars).
  //  - count series: no `valueField` → COUNT() of rows per argument value.
  const series = (d.series || []).map((s, i) => {
    const sRef = nextRef(), vRef = nextRef();
    const arg = `ArgumentDataMember="${xmlEscape(view)}.${xmlEscape(d.argument)}"`;
    const name = xmlEscape(s.caption || s.field || s.valueField || `Series${i + 1}`);
    if (s.valueField) {
      return `                <Item${i + 1} Ref="${sRef}" DataSource="#Ref-0" Name="${name}" SeriesID="${i}" ${arg} ValueDataMembersSerializable="${xmlEscape(view)}.${xmlEscape(s.valueField)}" ArgumentScaleType="Qualitative" ValueScaleType="Numerical">\n` +
        `                  <View Ref="${vRef}" TypeNameSerializable="${xmlEscape(viewType)}" />\n` +
        `                </Item${i + 1}>`;
    }
    const qRef = nextRef();
    return `                <Item${i + 1} Ref="${sRef}" DataSource="#Ref-0" Name="${name}" SeriesID="${i}" ${arg} ArgumentScaleType="Qualitative">\n` +
      `                  <View Ref="${vRef}" ColorEach="true" TypeNameSerializable="${xmlEscape(viewType)}" />\n` +
      `                  <QualitativeSummaryOptions Ref="${qRef}" SummaryFunction="${s.summary || 'COUNT()'}" />\n` +
      `                </Item${i + 1}>`;
  }).join('\n');

  const titleRef = nextRef();
  const chartRef = nextRef(), chartRef2 = nextRef(), dcRef = nextRef();
  const diaRef = nextRef(), axXRef = nextRef(), axYRef = nextRef(), legRef = nextRef();
  return `  <Bands>
    <Item1 Ref="${nextRef()}" ControlType="TopMarginBand" Name="TopMargin" HeightF="50" />
    <Item2 Ref="${nextRef()}" ControlType="ReportHeaderBand" Name="ReportHeader" HeightF="100">
      <Controls>
        <Item1 Ref="${titleRef}" ControlType="XRLabel" Name="lblTitle" Text="${xmlEscape(spec.title || spec.reportName)}" SizeF="750,30" LocationFloat="0,0" Font="Arial, 14pt, style=Bold" />
${kpis}
      </Controls>
    </Item2>
    <Item3 Ref="${nextRef()}" ControlType="DetailBand" Name="Detail" HeightF="320">
      <Controls>
        <Item1 Ref="${chartRef}" ControlType="XRChart" Name="chart1" DataSource="#Ref-0" SizeF="750,300" LocationFloat="0,0" Borders="None">
          <Chart Ref="${chartRef2}" PaletteName="Nature Colors">
            <DataContainer Ref="${dcRef}" DataMember="${xmlEscape(view)}" ValidateDataMembers="true">
              <SeriesSerializable>
${series}
              </SeriesSerializable>
            </DataContainer>
            <Diagram Ref="${diaRef}" TypeNameSerializable="XYDiagram">
              <AxisX Ref="${axXRef}" VisibleInPanesSerializable="-1" />
              <AxisY Ref="${axYRef}" VisibleInPanesSerializable="-1" />
            </Diagram>
            <Legend Ref="${legRef}" LegendID="-1" />
          </Chart>
        </Item1>
      </Controls>
    </Item3>
    <Item4 Ref="${nextRef()}" ControlType="BottomMarginBand" Name="BottomMargin" HeightF="50" />
  </Bands>`;
}

// ── assemble ─────────────────────────────────────────────────────────────────

function buildReportXml(spec) {
  if (!spec.sql) throw new Error('spec.sql is required');
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
  const pageW = spec.pageWidth || 850;
  const pageH = spec.pageHeight || 1100;

  return `<?xml version="1.0" encoding="utf-8"?>
<XtraReportsLayoutSerializer SerializerVersion="${DX.serializer}" Ref="1" ControlType="${DX.xtraReport}" Name="${xmlEscape(spec.reportName || 'Report')}"${landscape} Margins="50, 50, 50, 50" PageWidth="${pageW}" PageHeight="${pageH}" Version="${DX.version}" DataSource="#Ref-0">
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
