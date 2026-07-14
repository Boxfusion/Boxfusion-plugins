#!/usr/bin/env node
/**
 * Resolve project-specific metadata from a live Shesha site so nothing is hardcoded/guessed when
 * building a report (tables, columns, entity FKs, reference-list names/modules + item values,
 * report categories). Mirrors the ad-hoc API calls the skill would otherwise do by hand.
 *
 * Usage:
 *   node discover-metadata.js <baseUrl> <username> <password> <command> [arg]
 *
 * Commands:
 *   entities [substr]     List entity classes (id, className, tableName, module); optional filter.
 *   entity   <ClassName>  Resolve one entity: table, module, and its properties — highlighting
 *                         entity/FK and reference-list properties (with the FK column convention).
 *   reflist  <name>       Find reference list(s) by (short or full) name → full name + module + items
 *                         (item/itemValue). Lists every match so you can disambiguate duplicates.
 *   category              Items of the DevExpressReporting ReportCategory reference list.
 *
 * Output is JSON on stdout. Uses only Node built-ins. Sends the ngrok-skip header (harmless
 * elsewhere) so it also works through ngrok free tunnels.
 */

const http = require('http');
const https = require('https');
const { URL } = require('url');

const [baseUrlRaw, username, password, command, arg] = process.argv.slice(2);
if (!baseUrlRaw || !username || !password || !command) {
  console.error('Usage: node discover-metadata.js <baseUrl> <username> <password> <entities|entity|reflist|category> [arg]');
  process.exit(1);
}
const baseUrl = baseUrlRaw.replace(/\/+$/, '');

function request(method, path, { token, body } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(baseUrl + path);
    const lib = u.protocol === 'https:' ? https : http;
    const payload = body != null ? JSON.stringify(body) : null;
    const headers = { Accept: 'application/json', 'ngrok-skip-browser-warning': '1' };
    if (payload) { headers['Content-Type'] = 'application/json'; headers['Content-Length'] = Buffer.byteLength(payload); }
    if (token) headers.Authorization = `Bearer ${token}`;
    const req = lib.request({ method, hostname: u.hostname, port: u.port, path: u.pathname + u.search, headers }, (res) => {
      let d = ''; res.on('data', (c) => (d += c));
      res.on('end', () => { let j = null; try { j = d ? JSON.parse(d) : null; } catch { j = d; } resolve({ status: res.statusCode, body: j }); });
    });
    req.on('error', reject);
    req.setTimeout(60000, () => { req.destroy(new Error('request timeout')); });
    if (payload) req.write(payload);
    req.end();
  });
}

function fail(msg, res) {
  console.error(`✗ ${msg}`);
  if (res) console.error(`  HTTP ${res.status}: ${typeof res.body === 'string' ? res.body : JSON.stringify(res.body)}`);
  process.exit(1);
}

async function authenticate() {
  const res = await request('POST', '/api/TokenAuth/Authenticate', { body: { userNameOrEmailAddress: username, password } });
  if (res.status < 200 || res.status >= 300) fail('Authentication failed', res);
  const token = (res.body && (res.body.result?.accessToken || res.body.accessToken)) || null;
  if (!token) fail('No accessToken in auth response', res);
  return token;
}

async function listEntities(token) {
  const res = await request('GET', '/api/services/app/EntityConfig/GetMainDataList?maxResultCount=10000&sorting=className', { token });
  if (res.status !== 200) fail('EntityConfig/GetMainDataList failed', res);
  const items = res.body?.result?.items || [];
  return items.map((e) => ({ id: e.id, className: e.className, tableName: e.tableName, module: e.module }));
}

async function reflistMatches(token, name) {
  const res = await request('GET',
    `/api/services/app/Entities/GetAll?entityType=Shesha.Framework.ReferenceList&maxResultCount=200&quickSearch=${encodeURIComponent(name)}`, { token });
  if (res.status !== 200) fail('ReferenceList search failed', res);
  const items = res.body?.result?.items || [];
  // keep those whose name equals or ends with the requested (short) name
  const wanted = name.toLowerCase();
  const moduleName = (m) => (m && (m.name || m._displayName)) || m || null;
  return items
    .map((i) => ({ id: i.id, name: i.name, module: moduleName(i.module) }))
    .filter((i) => (i.name || '').toLowerCase() === wanted || (i.name || '').toLowerCase().endsWith('.' + wanted) || (i.name || '').toLowerCase().includes(wanted));
}

async function reflistItems(token, reflistId) {
  const res = await request('GET',
    `/api/services/app/Entities/GetAll?entityType=Shesha.Framework.ReferenceListItem&maxResultCount=200&filter=${encodeURIComponent(JSON.stringify({ '==': [{ var: 'referenceList' }, reflistId] }))}`, { token });
  if (res.status !== 200) return [];
  return (res.body?.result?.items || []).map((x) => ({ item: x.item, itemValue: x.itemValue })).sort((a, b) => a.itemValue - b.itemValue);
}

function print(obj) { process.stdout.write(JSON.stringify(obj, null, 2) + '\n'); }

(async () => {
  const token = await authenticate();

  if (command === 'entities') {
    let list = await listEntities(token);
    if (arg) { const s = arg.toLowerCase(); list = list.filter((e) => (e.className || '').toLowerCase().includes(s) || (e.tableName || '').toLowerCase().includes(s)); }
    print(list);
    return;
  }

  if (command === 'entity') {
    if (!arg) fail('entity <ClassName> required');
    const list = await listEntities(token);
    const matches = list.filter((e) => (e.className || '').toLowerCase() === arg.toLowerCase());
    const e = matches.find((m) => m.tableName && m.module) || matches[0];
    if (!e) fail(`Entity "${arg}" not found`);
    const mc = await request('GET', `/api/ModelConfigurations/${e.id}`, { token });
    const props = (mc.body?.result?.properties) || (mc.body?.properties) || [];
    const projected = props.map((p) => ({
      name: p.name, label: p.label, dataType: p.dataType,
      entityType: p.entityType || p.entityTypeShortAlias || null,
      referenceListName: p.referenceListName || null, referenceListModule: p.referenceListModule || null,
      // Shesha FK column convention for entity/navigation properties:
      fkColumn: p.dataType === 'entity' ? `${p.name}Id` : undefined,
    }));
    print({
      id: e.id, className: e.className, tableName: e.tableName, module: e.module,
      entityRefProps: projected.filter((p) => p.dataType === 'entity'),
      referenceListProps: projected.filter((p) => p.referenceListName),
      allProps: projected,
    });
    return;
  }

  if (command === 'reflist') {
    if (!arg) fail('reflist <name> required');
    const matches = await reflistMatches(token, arg);
    if (!matches.length) fail(`No reference list matching "${arg}"`);
    const out = [];
    for (const m of matches) out.push({ ...m, items: await reflistItems(token, m.id) });
    if (out.length > 1) {
      console.error(`⚠ ${out.length} reference lists match "${arg}" — pick the correct full name/module for the column you are mapping (item values may differ between them).`);
    }
    print(out);
    return;
  }

  if (command === 'category') {
    const matches = (await reflistMatches(token, 'ReportCategory')).filter((m) => /DevExpressReporting\.ReportCategory$/i.test(m.name));
    const m = matches[0] || (await reflistMatches(token, 'ReportCategory'))[0];
    if (!m) fail('ReportCategory reference list not found');
    print({ ...m, items: await reflistItems(token, m.id) });
    return;
  }

  fail(`Unknown command "${command}"`);
})().catch((e) => { console.error(e.message || e); process.exit(1); });
