#!/usr/bin/env node
/**
 * Create OR update a DevExpress report on a live Shesha site (filter form + ReportingReport +
 * ReportingReportParameter rows) via the REST API. Updates modify the existing records in place —
 * the report is never deleted and recreated.
 *
 * Usage:
 *   node deploy-report.js <baseUrl> <username> <password> <deploy.json> [options]
 *
 * Options:
 *   --report-id <guid>        Update the existing report with this id (instead of creating one).
 *                             (Equivalent to setting report.id in deploy.json.)
 *   --upsert                  No id? Look the report up by report.displayName and UPDATE it if
 *                             exactly one exists (else CREATE; errors if the name is ambiguous).
 *   --prune-params            When updating, delete parameters that exist on the report but are no
 *                             longer in the spec. Default: keep them (only add/update).
 *   --dry-run                 Print the planned requests without sending them.
 *   --module-route <segment>  Report service route segment (default: DevExpressReporting).
 *   --report-entity-type <t>  Entity type used for the --upsert name lookup
 *                             (default: boxfusion.devexpressreporting.Domain.ReportingReport).
 *
 * Mode: report.id/--report-id → UPDATE by id; --upsert → find by name then update-or-create;
 * otherwise → CREATE.
 *
 * deploy.json shape (see reference/api-access.md):
 * {
 *   "report": {
 *     "id",                        // OPTIONAL — presence triggers update of that report
 *     "displayName", "description", "reportType", "category", "connectionStringName",
 *     "orderIndex", "showInReportsMenu",
 *     "reportDefinitionXml"        // inline, OR
 *     "reportDefinitionXmlFile"    // path to the XML file built by build-report-xml.js
 *   },
 *   "form": {                      // optional; omit when the report has no filters
 *     "module", "name", "label", "description",
 *     "markup" | "markupFile"
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
  else if (argv[i] === '--prune-params') flags.prune = true;
  else if (argv[i] === '--upsert') flags.upsert = true;
  else if (argv[i] === '--module-route') flags.moduleRoute = argv[++i];
  else if (argv[i] === '--report-id') flags.reportId = argv[++i];
  else if (argv[i] === '--report-entity-type') flags.reportEntityType = argv[++i];
  else positional.push(argv[i]);
}
const [baseUrlRaw, username, password, deployPath] = positional;
if (!baseUrlRaw || !username || !password || !deployPath) {
  console.error('Usage: node deploy-report.js <baseUrl> <username> <password> <deploy.json> [--report-id <guid>] [--upsert] [--prune-params] [--dry-run] [--module-route <seg>]');
  process.exit(1);
}
const baseUrl = baseUrlRaw.replace(/\/+$/, '');
const moduleRoute = flags.moduleRoute || 'DevExpressReporting';
// Generic entity type used to look a report up by name (bypasses the report AppService's list mapper).
const REPORT_ENTITY_TYPE = flags.reportEntityType || 'boxfusion.devexpressreporting.Domain.ReportingReport';

// ── http helper ────────────────────────────────────────────────────────────

function request(method, url, { token, body } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const lib = u.protocol === 'https:' ? https : http;
    const payload = body != null ? JSON.stringify(body) : null;
    const headers = { Accept: 'application/json', 'ngrok-skip-browser-warning': '1' };
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
    req.setTimeout(60000, () => req.destroy(new Error('request timeout')));
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
function idOf(res) { return res && res.body && (res.body.result?.id || res.body.id); }

// ── load deploy spec ─────────────────────────────────────────────────────────

function readMaybeFile(inline, file) {
  if (file) return fs.readFileSync(file, 'utf8');
  return inline;
}

const spec = JSON.parse(fs.readFileSync(deployPath, 'utf8'));
const reportSpec = spec.report || {};
reportSpec.reportDefinitionXml = readMaybeFile(reportSpec.reportDefinitionXml, reportSpec.reportDefinitionXmlFile);
if (!reportSpec.reportDefinitionXml) fail('report.reportDefinitionXml (or reportDefinitionXmlFile) is required');

let reportId = flags.reportId || reportSpec.id || null;   // present ⇒ update by id
let updating = !!reportId;                                // may also be set by --upsert name lookup

let formMarkupString = null;
if (spec.form) {
  const raw = readMaybeFile(spec.form.markup, spec.form.markupFile);
  formMarkupString = typeof raw === 'string' ? raw : JSON.stringify(raw);
}

// ── shared calls ─────────────────────────────────────────────────────────────

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

// Find report(s) by displayName via the generic entity query (the report AppService's own GetAll can
// be broken by a DTO mapping bug, so we go through Entities/GetAll which doesn't hit that mapper).
async function resolveReportIdByName(token, displayName) {
  if (!displayName) fail('--upsert needs report.displayName in the spec');
  const filter = encodeURIComponent(JSON.stringify({ '==': [{ var: 'displayName' }, displayName] }));
  const res = await request('GET',
    `${baseUrl}/api/services/app/Entities/GetAll?entityType=${encodeURIComponent(REPORT_ENTITY_TYPE)}&maxResultCount=50&properties=id displayName&filter=${filter}`, { token });
  if (!ok(res)) fail('Report name lookup (Entities/GetAll) failed — pass --report-id instead', res);
  return (res.body?.result?.items || []).map((i) => ({ id: i.id, displayName: i.displayName }));
}

// ── form: create+publish, or update markup in place ──────────────────────────

async function deployForm(token) {
  if (!spec.form) return null;
  const { module, name, label, description } = spec.form;
  const parameterFormPath = JSON.stringify({ name, module });
  if (flags.dryRun) {
    console.log(`\n[dry-run] ${updating ? 'Update' : 'Create'} form: ${module}/${name}`);
    return parameterFormPath;
  }

  // Does a live form with this name already exist?
  const existing = await request('GET', `${baseUrl}/api/services/Shesha/FormConfiguration/GetByName?module=${encodeURIComponent(module)}&name=${encodeURIComponent(name)}`, { token });
  let formId = ok(existing) ? idOf(existing) : null;

  if (!formId) {
    const moduleId = await resolveModuleId(token, module);
    const createRes = await request('POST', `${baseUrl}/api/services/Shesha/FormConfiguration/Create`, {
      token, body: { moduleId, name, label: label || name, description: description || '' },
    });
    if (!ok(createRes)) fail('FormConfiguration/Create failed', createRes);
    formId = idOf(createRes);
    if (!formId) fail('No form id returned from Create', createRes);
  }

  const markupRes = await request('PUT', `${baseUrl}/api/services/Shesha/FormConfiguration/UpdateMarkup`, {
    token, body: { id: formId, markup: formMarkupString },
  });
  if (!ok(markupRes)) fail('FormConfiguration/UpdateMarkup failed', markupRes);

  // Ensure it is Live (status 3). Harmless if already live.
  const statusRes = await request('PUT', `${baseUrl}/api/services/Shesha/FormConfiguration/UpdateStatus`, {
    token, body: { filter: JSON.stringify({ '==': [{ var: 'id' }, formId] }), status: 3 },
  });
  if (!ok(statusRes)) fail('FormConfiguration/UpdateStatus (publish) failed', statusRes);

  console.log(`✓ Form ${existing && idOf(existing) ? 'updated' : 'created'} & published: ${module}/${name} (id ${formId})`);
  return parameterFormPath;
}

// ── report: create, or update the existing DTO in place ──────────────────────

function reportOverrides(parameterFormPath, formProcessed) {
  const o = { reportDefinitionXml: reportSpec.reportDefinitionXml };
  const copy = ['displayName', 'description', 'reportType', 'category', 'connectionStringName', 'orderIndex', 'showInReportsMenu'];
  for (const k of copy) if (reportSpec[k] !== undefined) o[k] = reportSpec[k];
  if (formProcessed) { o.parameterFormPath = parameterFormPath; o.useCustomParameters = !!parameterFormPath; }
  return o;
}

async function createReport(token, parameterFormPath, formProcessed) {
  const payload = {
    displayName: reportSpec.displayName,
    description: reportSpec.description || '',
    reportType: reportSpec.reportType ?? 1,
    category: reportSpec.category,
    connectionStringName: reportSpec.connectionStringName || 'Default',
    orderIndex: reportSpec.orderIndex ?? 0,
    showInReportsMenu: reportSpec.showInReportsMenu ?? true,
    reportDefinitionXml: reportSpec.reportDefinitionXml,
    useCustomParameters: formProcessed ? !!parameterFormPath : false,
    parameterFormPath: formProcessed ? parameterFormPath : null,
  };
  if (flags.dryRun) {
    console.log('\n[dry-run] Create report:');
    console.log(JSON.stringify({ ...payload, reportDefinitionXml: `<${payload.reportDefinitionXml.length} chars>` }, null, 2));
    return 'dry-run-report-id';
  }
  const res = await request('POST', `${baseUrl}/api/services/${moduleRoute}/ReportingReport/Create`, { token, body: payload });
  if (!ok(res)) fail('ReportingReport/Create failed', res);
  const id = idOf(res);
  if (!id) fail('No report id returned from Create', res);
  console.log(`✓ Report created: ${payload.displayName} (id ${id})`);
  return id;
}

async function updateReport(token, parameterFormPath, formProcessed) {
  if (flags.dryRun) {
    console.log(`\n[dry-run] Update report ${reportId} with:`, Object.keys(reportOverrides(parameterFormPath, formProcessed)).join(', '));
    return reportId;
  }
  const getRes = await request('GET', `${baseUrl}/api/services/${moduleRoute}/ReportingReport/Get?id=${reportId}`, { token });
  if (!ok(getRes) || !getRes.body?.result) fail(`ReportingReport/Get failed for id ${reportId} (does it exist?)`, getRes);
  const merged = { ...getRes.body.result, ...reportOverrides(parameterFormPath, formProcessed) };
  const res = await request('PUT', `${baseUrl}/api/services/${moduleRoute}/ReportingReport/Update`, { token, body: merged });
  if (!ok(res)) fail('ReportingReport/Update failed', res);
  console.log(`✓ Report updated in place: ${merged.displayName} (id ${reportId})`);
  return reportId;
}

// ── parameters: create (new report) or reconcile (update) ────────────────────

function paramPayload(p, reportId) {
  return {
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
}

async function createParameters(token, reportId) {
  for (const p of spec.parameters || []) {
    if (flags.dryRun) { console.log(`[dry-run] Create parameter "${p.internalName}"`); continue; }
    const res = await request('POST', `${baseUrl}/api/services/${moduleRoute}/ReportingReportParameter/Create`, { token, body: paramPayload(p, reportId) });
    if (!ok(res)) fail(`ReportingReportParameter/Create failed for "${p.internalName}"`, res);
    console.log(`✓ Parameter created: ${p.internalName}`);
  }
}

async function reconcileParameters(token, reportId) {
  const specParams = spec.parameters || [];
  if (flags.dryRun) {
    console.log(`[dry-run] Reconcile parameters: upsert ${specParams.map((p) => p.internalName).join(', ') || '(none)'}${flags.prune ? ' + prune obsolete' : ''}`);
    return;
  }
  const getRes = await request('GET', `${baseUrl}/api/services/${moduleRoute}/ReportingReport/GetParameters?reportId=${reportId}`, { token });
  const existing = (ok(getRes) && Array.isArray(getRes.body?.result)) ? getRes.body.result : [];
  const byName = new Map(existing.map((e) => [e.internalName, e]));
  const specNames = new Set(specParams.map((p) => p.internalName));

  for (const p of specParams) {
    const cur = byName.get(p.internalName);
    if (cur) {
      const merged = { ...cur, ...paramPayload(p, reportId), id: cur.id };
      const res = await request('PUT', `${baseUrl}/api/services/${moduleRoute}/ReportingReportParameter/Update`, { token, body: merged });
      if (!ok(res)) fail(`ReportingReportParameter/Update failed for "${p.internalName}"`, res);
      console.log(`✓ Parameter updated: ${p.internalName}`);
    } else {
      const res = await request('POST', `${baseUrl}/api/services/${moduleRoute}/ReportingReportParameter/Create`, { token, body: paramPayload(p, reportId) });
      if (!ok(res)) fail(`ReportingReportParameter/Create failed for "${p.internalName}"`, res);
      console.log(`✓ Parameter created: ${p.internalName}`);
    }
  }

  const obsolete = existing.filter((e) => !specNames.has(e.internalName));
  for (const e of obsolete) {
    if (flags.prune) {
      const res = await request('DELETE', `${baseUrl}/api/services/${moduleRoute}/ReportingReportParameter/Delete?id=${e.id}`, { token });
      if (!ok(res)) fail(`ReportingReportParameter/Delete failed for "${e.internalName}"`, res);
      console.log(`✓ Parameter pruned: ${e.internalName}`);
    } else {
      console.log(`• Obsolete parameter kept (use --prune-params to remove): ${e.internalName}`);
    }
  }
}

// ── main ─────────────────────────────────────────────────────────────────────

async function main() {
  // --upsert needs a name lookup (a read), so authenticate even for a dry run in that case.
  const token = (!flags.dryRun || flags.upsert) ? await authenticate() : 'dry-run-token';

  if (!reportId && flags.upsert) {
    const matches = await resolveReportIdByName(token, reportSpec.displayName);
    if (matches.length === 1) { reportId = matches[0].id; updating = true; console.log(`↻ Matched existing report "${reportSpec.displayName}" → ${reportId}`); }
    else if (matches.length === 0) { console.log(`＋ No report named "${reportSpec.displayName}" found — will create a new one`); }
    else fail(`${matches.length} reports are named "${reportSpec.displayName}" — ambiguous. Pass the exact id with --report-id:\n` + matches.map((m) => `    ${m.id}`).join('\n'));
  }

  console.log(`Target: ${baseUrl}  (module route: ${moduleRoute})  mode: ${updating ? 'UPDATE ' + reportId : 'CREATE'}${flags.dryRun ? '  [DRY RUN]' : ''}`);
  const formProcessed = !!spec.form;
  const parameterFormPath = await deployForm(token);
  const id = updating
    ? await updateReport(token, parameterFormPath, formProcessed)
    : await createReport(token, parameterFormPath, formProcessed);
  if (updating) await reconcileParameters(token, id);
  else await createParameters(token, id);
  console.log('\nDone.');
  if (!flags.dryRun) console.log(`Verify: GET ${baseUrl}/api/services/${moduleRoute}/ReportingReport/Get?id=${id}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
