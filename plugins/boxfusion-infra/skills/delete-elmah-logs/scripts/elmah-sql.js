// Runs ON a Linux App Service (Kudu container), detached via nohup/setsid by kudu-elmah.sh.
// Sizes, counts or deletes Shesha.Elmah rows (elmah.errors + orphaned elmah.error_refs) in the app's own
// SQL Server database, using the app's Default connection string. Never prints the connection string.
// Needs the mssql npm package; kudu-elmah.sh installs it into the work dir.
//
// Usage: node elmah-sql.js <histogram|count|delete> <older-than-days> [batch-size] [work-dir]
//   histogram: size, rows per application and month, top error types (older than / within <days>)
//   count:     rows older than <days>
//   delete:    delete rows older than <days> in batches (min 1 day), then orphaned error_refs

const fs = require('fs');
const path = require('path');

const [mode, daysArg, batchArg, workArg] = process.argv.slice(2);
const work = workArg || '/home/LogFiles/elmah-sql';
const days = parseInt(daysArg, 10);
const batch = parseInt(batchArg || '5000', 10);

fs.mkdirSync(work, { recursive: true });
const statusFile = path.join(work, 'status');
const progressFile = path.join(work, 'progress');
const pidFile = path.join(work, 'pid');
const errorsFile = path.join(work, 'errors.log');

const now = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
const write = (f, lines) => fs.writeFileSync(f, lines.join('\n') + '\n');
const fail = (m) => { write(statusFile, [`state=error`, `message=${m}`]); try { fs.unlinkSync(pidFile); } catch {} process.exit(2); };

try {
  const old = parseInt(fs.readFileSync(pidFile, 'utf8'), 10);
  process.kill(old, 0);
  console.error(`already running (pid ${old})`);
  process.exit(1);
} catch {}
fs.writeFileSync(pidFile, String(process.pid));

if (!['histogram', 'count', 'delete'].includes(mode)) fail(`unknown-mode-${mode}`);
if (!Number.isInteger(days) || days < 0) fail('days-must-be-a-number');
if (mode === 'delete' && days < 1) fail('days-must-be-at-least-1');

// App Service exposes connection strings as env vars; fall back to the deployed appsettings.
function connectionString() {
  for (const k of ['SQLAZURECONNSTR_Default', 'SQLCONNSTR_Default', 'CUSTOMCONNSTR_Default',
                   'APPSETTING_ConnectionStrings__Default', 'ConnectionStrings__Default']) {
    if (process.env[k]) return process.env[k];
  }
  for (const f of ['appsettings.Production.json', 'appsettings.json']) {
    try {
      const j = JSON.parse(fs.readFileSync(path.join('/home/site/wwwroot', f), 'utf8').replace(/^﻿/, ''));
      if (j.ConnectionStrings && j.ConnectionStrings.Default) return j.ConnectionStrings.Default;
    } catch {}
  }
  return null;
}

// ADO.NET connection string -> tedious config. mssql's own parser ignores .NET synonyms such as "User".
function toConfig(cs) {
  const kv = {};
  for (const part of cs.split(';')) {
    const i = part.indexOf('=');
    if (i > 0) kv[part.slice(0, i).trim().toLowerCase()] = part.slice(i + 1).trim();
  }
  const pick = (...keys) => keys.map(k => kv[k]).find(v => v !== undefined);
  const yes = v => /^(true|yes|1|mandatory|strict)$/i.test(v || '');
  const [server, port] = (pick('data source', 'server', 'address', 'addr', 'network address') || '')
    .replace(/^tcp:/i, '').split(',');
  return {
    server,
    port: port ? parseInt(port, 10) : 1433,
    database: pick('initial catalog', 'database'),
    user: pick('user id', 'uid', 'user', 'username', 'user name'),
    password: pick('password', 'pwd'),
    requestTimeout: 600000,
    options: {
      encrypt: kv.encrypt === undefined ? true : yes(kv.encrypt),
      trustServerCertificate: yes(kv.trustservercertificate),
    },
  };
}

async function main() {
  // The Linux Kudu image has node + npm but no SQL client, so install mssql into the work dir on first use.
  // npm needs a package.json there, or it fails with 'Tracker "idealTree" already exists'.
  // An interrupted install leaves packages missing, so if mssql won't load, reinstall from scratch once.
  const load = () => require(path.join(work, 'node_modules', 'mssql'));
  let sql;
  try { sql = load(); } catch {
    write(statusFile, ['state=installing-mssql', `started_utc=${now()}`]);
    fs.rmSync(path.join(work, 'node_modules'), { recursive: true, force: true });
    fs.writeFileSync(path.join(work, 'package.json'), '{}\n');
    require('child_process').execSync('npm install --no-audit --no-fund --silent mssql@10.0.4',
      { cwd: work, stdio: ['ignore', 'ignore', fs.openSync(path.join(work, 'npm.log'), 'w')] });
    // drop the half-loaded modules the failed attempt left in the require cache
    for (const k of Object.keys(require.cache)) if (k.startsWith(path.join(work, 'node_modules'))) delete require.cache[k];
    sql = load();
  }
  const cs = connectionString();
  if (!cs) fail('no-default-connection-string');

  const pool = await new sql.ConnectionPool(toConfig(cs)).connect();
  const q = async (text, params = {}) => {
    const r = pool.request();
    for (const [k, v] of Object.entries(params)) r.input(k, v);
    return (await r.query(text)).recordset;
  };

  const db = (await q('SELECT DB_NAME() AS name'))[0].name;
  const header = [`mode=${mode}`, `database=${db}`, `older_than_days=${days}`];
  write(statusFile, ['state=running', ...header, `started_utc=${now()}`]);
  fs.writeFileSync(progressFile, '0\n');

  if (!(await q("SELECT OBJECT_ID('elmah.errors', 'U') AS id"))[0].id) {
    write(statusFile, ['state=done', ...header, 'elmah_table=missing', `finished_utc=${now()}`]);
    return;
  }

  const cutoff = new Date(Date.now() - days * 86400000);
  const size = async () => (await q(`
    SELECT CAST(SUM(a.total_pages) * 8 / 1024 AS int) AS mb FROM sys.partitions p
    JOIN sys.allocation_units a ON a.container_id = p.partition_id
    WHERE p.object_id IN (OBJECT_ID('elmah.errors'), OBJECT_ID('elmah.error_refs'))`))[0].mb;
  const older = async () => (await q('SELECT COUNT_BIG(*) AS n FROM elmah.errors WHERE time_utc < @cutoff', { cutoff }))[0].n;

  if (mode === 'histogram') {
    const out = ['state=done', ...header, `elmah_mb=${await size()}`,
      `db_mb=${(await q('SELECT CAST(SUM(CAST(size AS bigint)) * 8 / 1024 AS int) AS mb FROM sys.database_files'))[0].mb}`,
      `refs=${(await q('SELECT COUNT_BIG(*) AS n FROM elmah.error_refs'))[0].n}`, 'rows_by_application:'];
    for (const r of await q('SELECT application, COUNT_BIG(*) AS n, MIN(time_utc) AS oldest, MAX(time_utc) AS newest FROM elmah.errors GROUP BY application ORDER BY n DESC'))
      out.push(`  ${r.n} ${r.application} ${r.oldest && r.oldest.toISOString().slice(0, 10)}..${r.newest && r.newest.toISOString().slice(0, 10)}`);
    out.push('rows_by_month:');
    for (const r of await q('SELECT CONVERT(char(7), time_utc, 126) AS m, COUNT_BIG(*) AS n FROM elmah.errors GROUP BY CONVERT(char(7), time_utc, 126) ORDER BY m'))
      out.push(`  ${r.n} ${r.m}`);
    const types = await q(`
      SELECT CASE WHEN time_utc < @cutoff THEN 'older' ELSE 'recent' END AS age, type, LEFT(message, 110) AS msg, COUNT_BIG(*) AS n
      FROM elmah.errors GROUP BY CASE WHEN time_utc < @cutoff THEN 'older' ELSE 'recent' END, type, LEFT(message, 110)`, { cutoff });
    for (const age of ['older', 'recent']) {
      out.push(`top_types_${age}:`);
      types.filter(t => t.age === age).sort((a, b) => Number(b.n) - Number(a.n)).slice(0, 10)
        .forEach(t => out.push(`  ${t.n} ${t.type} | ${(t.msg || '').replace(/\s+/g, ' ')}`));
    }
    out.push(`rows_older_than_cutoff=${await older()}`, `finished_utc=${now()}`);
    write(statusFile, out);
    return;
  }

  if (mode === 'count') {
    write(statusFile, ['state=done', ...header, `matched=${await older()}`, `elmah_mb=${await size()}`, `finished_utc=${now()}`]);
    return;
  }

  // delete: one application at a time so each batch seeks ix_errors_app_time_seq instead of scanning the heap.
  // Each batch is its own short transaction, so the live app keeps logging. TABLOCK lets the heap free its pages.
  let deleted = 0;
  const apps = (await q('SELECT DISTINCT application FROM elmah.errors')).map(r => r.application);
  for (const app of apps) {
    for (;;) {
      const r = await pool.request().input('app', app).input('cutoff', cutoff).input('batch', batch)
        .query('DELETE TOP (@batch) FROM elmah.errors WITH (TABLOCK) WHERE application = @app AND time_utc < @cutoff');
      deleted += r.rowsAffected[0];
      fs.writeFileSync(progressFile, `${deleted}\n`);
      if (r.rowsAffected[0] === 0) break;
    }
  }
  // error_refs has no foreign key, so remove refs whose error is gone.
  let refs = 0;
  for (;;) {
    const r = await pool.request().input('batch', batch).query(`
      DELETE TOP (@batch) r FROM elmah.error_refs r
      WHERE NOT EXISTS (SELECT 1 FROM elmah.errors e WHERE e.error_id = r.error_id)`);
    refs += r.rowsAffected[0];
    if (r.rowsAffected[0] === 0) break;
  }
  write(statusFile, ['state=done', ...header, `deleted=${deleted}`, `orphan_refs_deleted=${refs}`,
    `rows_remaining=${(await q('SELECT COUNT_BIG(*) AS n FROM elmah.errors'))[0].n}`, `elmah_mb=${await size()}`, `finished_utc=${now()}`]);
}

main()
  .catch(e => { fs.appendFileSync(errorsFile, `${now()} ${e.message}\n`); fail('see-errors.log'); })
  .finally(() => { try { fs.unlinkSync(pidFile); } catch {} process.exit(0); });
