#!/usr/bin/env node
/**
 * Deploy a DevExpress report to a live Shesha site: create the filter form,
 * the ReportingReport, and its ReportingReportParameter rows via the REST API.
 *
 * Usage:
 *   node deploy-report.js <baseUrl> <username> <password> <deploy.json> [options]
 *
 * Options:
 *   --dry-run                 Print the planned requests without sending them.
 *   --module-route <segment>  Report service route segment (default: DevExpressReporting).
 *
 * deploy.json shape (see reference/api-access.md):
 * {
 *   "report": {
 *     "displayName", "description", "reportType", "category", "connectionStringName",
 *     "orderIndex", "showInReportsMenu",
 *     "reportDefinitionXml"      // inline, OR
 *     "reportDefinitionXmlFile"  // path to the XML file built by build-report-xml.js
 *   },
 *   "form": {                    // optional; omit when the report has no filters
 *     "module", "name", "label", "description",
 *     "markup"        // inline JSON string/object, OR
 *     "markupFile"    // path to the form markup JSON
 *   },
 *   "parameters": [ { "internalName", "displayName", "type", "columnName", "parameterOrderIndex",
 *                     "referenceListName", "referenceListNamespace", "entityTypeShortAlias",
 *                     "hideParameter", "parameterValue" } ]
 * }
 *
 * Uses only Node built-ins (https/http/fs). No npm install required.
 */

const fs = require('fs');
const http = require('http');
const https = require('https');
const { URL } = require('url');

// ── args ─────────────────────────────────────────────────────────────────────

const argv = process.argv.slice(2);
const flags = {};
const positional = [];
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--dry-run') flags.dryRun = true;
  else if (argv[i] === '--module-route') flags.moduleRoute = argv[++i];
  else positional.push(argv[i]);
}
const [baseUrlRaw, username, password, deployPath] = positional;
if (!baseUrlRaw || !username || !password || !deployPath) {
  console.error('Usage: node deploy-report.js <baseUrl> <username> <password> <deploy.json> [--dry-run] [--module-route <seg>]');
  process.exit(1);
}
const baseUrl = baseUrlRaw.replace(/\/+$/, '');
const moduleRoute = flags.moduleRoute || 'DevExpressReporting';

// ── http helper ────────────────────────────────────────────────────────────

function request(method, url, { token, body } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const lib = u.protocol === 'https:' ? https : http;
    const payload = body != null ? JSON.stringify(body) : null;
    const headers = { Accept: 'application/json' };
    if (payload) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(payload);
    }
    if (token) headers.Authorization = `Bearer ${token}`;
    const req = lib.request(
      { method, hostname: u.hostname, port: u.port, path: u.pathname + u.search, headers },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          let parsed = null;
          try { parsed = data ? JSON.parse(data) : null; } catch { parsed = data; }
          resolve({ status: res.statusCode, body: parsed, raw: data });
        });
      }
    );
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function ok(res) { return res.status >= 200 && res.status < 300; }

function fail(msg, res) {
  console.error(`\n✗ ${msg}`);
  if (res) console.error(`  HTTP ${res.status}: ${typeof res.body === 'string' ? res.body : JSON.stringify(res.body)}`);
  process.exit(1);
}

// ── load deploy spec ─────────────────────────────────────────────────────────

function readMaybeFile(inline, file, asString) {
  if (file) {
    const content = fs.readFileSync(file, 'utf8');
    return asString ? content : content;
  }
  return inline;
}

const spec = JSON.parse(fs.readFileSync(deployPath, 'utf8'));
const reportSpec = spec.report || {};
reportSpec.reportDefinitionXml = readMaybeFile(reportSpec.reportDefinitionXml, reportSpec.reportDefinitionXmlFile, true);
if (!reportSpec.reportDefinitionXml) fail('report.reportDefinitionXml (or reportDefinitionXmlFile) is required');

let formMarkupString = null;
if (spec.form) {
  const raw = readMaybeFile(spec.form.markup, spec.form.markupFile, true);
  formMarkupString = typeof raw === 'string' ? raw : JSON.stringify(raw);
}

// ── flow ─────────────────────────────────────────────────────────────────────

async function authenticate() {
  const res = await request('POST', `${baseUrl}/api/TokenAuth/Authenticate`, {
    body: { userNameOrEmailAddress: username, password },
  });
  if (!ok(res)) fail('Authentication failed', res);
  const token = (res.body && (res.body.result?.accessToken || res.body.accessToken)) || null;
  if (!token) fail('No accessToken in auth response', res);
  return token;
}

async function resolveModuleId(token, moduleName) {
  const res = await request('GET', `${baseUrl}/api/services/app/Module/GetAll?maxResultCount=1000`, { token });
  if (!ok(res)) fail('Module/GetAll failed', res);
  const items = res.body?.result?.items || res.body?.result || [];
  const found = items.find((m) => (m.name || '').toLowerCase() === moduleName.toLowerCase());
  if (!found) fail(`Module "${moduleName}" not found on target site`);
  return found.id;
}

async function createForm(token) {
  if (!spec.form) return null;
  const { module, name, label, description } = spec.form;
  if (flags.dryRun) {
    console.log('\n[dry-run] Create form:');
    console.log(JSON.stringify({ module, name, label, description, markup: '<markup omitted>' }, null, 2));
    return JSON.stringify({ name, module });
  }
  const moduleId = await resolveModuleId(token, module);
  const createRes = await request('POST', `${baseUrl}/api/services/Shesha/FormConfiguration/Create`, {
    token, body: { moduleId, name, label: label || name, description: description || '' },
  });
  if (!ok(createRes)) fail('FormConfiguration/Create failed (verify the create payload against Swagger)', createRes);
  const formId = createRes.body?.result?.id || createRes.body?.id;
  if (!formId) fail('No form id returned from Create', createRes);

  // Set the markup (PUT, not POST) then publish the draft so the runtime can resolve it.
  const markupRes = await request('PUT', `${baseUrl}/api/services/Shesha/FormConfiguration/UpdateMarkup`, {
    token, body: { id: formId, markup: formMarkupString },
  });
  if (!ok(markupRes)) fail('FormConfiguration/UpdateMarkup failed', markupRes);

  // Publish: status 3 = Live. Filter is jsonLogic selecting this form id.
  const statusRes = await request('PUT', `${baseUrl}/api/services/Shesha/FormConfiguration/UpdateStatus`, {
    token, body: { filter: JSON.stringify({ '==': [{ var: 'id' }, formId] }), status: 3 },
  });
  if (!ok(statusRes)) fail('FormConfiguration/UpdateStatus (publish) failed', statusRes);

  console.log(`✓ Form created & published: ${module}/${name} (id ${formId})`);
  return JSON.stringify({ name, module });
}

async function createReport(token, parameterFormPath) {
  const payload = {
    displayName: reportSpec.displayName,
    description: reportSpec.description || '',
    reportType: reportSpec.reportType ?? 1,
    category: reportSpec.category,
    connectionStringName: reportSpec.connectionStringName || 'Default',
    orderIndex: reportSpec.orderIndex ?? 0,
    showInReportsMenu: reportSpec.showInReportsMenu ?? true,
    reportDefinitionXml: reportSpec.reportDefinitionXml,
    useCustomParameters: !!parameterFormPath,
    parameterFormPath: parameterFormPath || null,
  };
  if (flags.dryRun) {
    console.log('\n[dry-run] Create report:');
    console.log(JSON.stringify({ ...payload, reportDefinitionXml: `<${payload.reportDefinitionXml.length} chars>` }, null, 2));
    return 'dry-run-report-id';
  }
  const res = await request('POST', `${baseUrl}/api/services/${moduleRoute}/ReportingReport/Create`, { token, body: payload });
  if (!ok(res)) fail('ReportingReport/Create failed', res);
  const id = res.body?.result?.id || res.body?.id;
  if (!id) fail('No report id returned from Create', res);
  console.log(`✓ Report created: ${payload.displayName} (id ${id})`);
  return id;
}

async function createParameters(token, reportId) {
  const params = spec.parameters || [];
  for (const p of params) {
    const payload = {
      reportingReport: { id: reportId },
      internalName: p.internalName,
      displayName: p.displayName || p.internalName,
      type: typeof p.type === 'object' ? p.type : { itemValue: p.type },
      columnName: p.columnName || null,
      description: p.description || '',
      hideParameter: !!p.hideParameter,
      parameterValue: p.parameterValue || null,
      parameterOrderIndex: p.parameterOrderIndex ?? 0,
      referenceListName: p.referenceListName || null,
      referenceListNamespace: p.referenceListNamespace || null,
      entityTypeShortAlias: p.entityTypeShortAlias || null,
    };
    if (flags.dryRun) {
      console.log(`\n[dry-run] Create parameter "${p.internalName}":`);
      console.log(JSON.stringify(payload, null, 2));
      continue;
    }
    const res = await request('POST', `${baseUrl}/api/services/${moduleRoute}/ReportingReportParameter/Create`, { token, body: payload });
    if (!ok(res)) fail(`ReportingReportParameter/Create failed for "${p.internalName}"`, res);
    console.log(`✓ Parameter created: ${p.internalName}`);
  }
}

async function main() {
  console.log(`Target: ${baseUrl}  (module route: ${moduleRoute})${flags.dryRun ? '  [DRY RUN]' : ''}`);
  const token = flags.dryRun ? 'dry-run-token' : await authenticate();
  const parameterFormPath = await createForm(token);
  const reportId = await createReport(token, parameterFormPath);
  await createParameters(token, reportId);
  console.log('\nDone.');
  if (!flags.dryRun) {
    console.log(`Verify: GET ${baseUrl}/api/services/${moduleRoute}/ReportingReport/Get?id=${reportId}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
