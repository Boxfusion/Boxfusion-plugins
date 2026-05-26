#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const REPO_ROOT = path.resolve(__dirname, '..');
const REPORTS_ROOT = path.join(REPO_ROOT, 'test-reports');
const OUT_DIR = path.join(REPO_ROOT, 'allure-results');

const APP_NAME = '__APP_NAME__';
const APP_URL = '__APP_URL__';

function uuid() { return crypto.randomUUID(); }
function hashId(str) { return crypto.createHash('md5').update(str).digest('hex'); }

function mdToHtml(md) {
  const escaped = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const lines = escaped.split('\n');
  const out = [];
  let inCode = false, inList = false;

  for (const line of lines) {
    if (/^```/.test(line)) {
      if (inCode) { out.push('</code></pre>'); inCode = false; }
      else { if (inList) { out.push('</ul>'); inList = false; } out.push('<pre><code>'); inCode = true; }
      continue;
    }
    if (inCode) { out.push(line); continue; }
    if (line.trim() === '') { if (inList) { out.push('</ul>'); inList = false; } out.push('<br/>'); continue; }

    const bullet = line.match(/^-\s+(.+)$/);
    if (bullet) {
      if (!inList) { out.push('<ul>'); inList = true; }
      let c = bullet[1];
      c = c.replace(/\[PASS\]/g, '<span style="color:#22c55e;font-weight:bold">&#x2705; PASS</span>');
      c = c.replace(/\[FAIL\]/g, '<span style="color:#ef4444;font-weight:bold">&#x274c; FAIL</span>');
      c = c.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      c = c.replace(/`([^`]+)`/g, '<code>$1</code>');
      out.push(`<li>${c}</li>`); continue;
    }
    if (inList) { out.push('</ul>'); inList = false; }
    if (/^&gt;\s*/.test(line)) {
      let c = line.replace(/^(&gt;\s*)+/, '');
      c = c.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      c = c.replace(/`([^`]+)`/g, '<code>$1</code>');
      out.push(`<blockquote>${c}</blockquote>`); continue;
    }
    let html = line;
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    out.push(`<p>${html}</p>`);
  }
  if (inList) out.push('</ul>');
  if (inCode) out.push('</code></pre>');
  return out.join('\n');
}

function parseReport(mdPath) {
  const raw = fs.readFileSync(mdPath, 'utf8');
  const lines = raw.split(/\r?\n/);
  const meta = {};
  for (const line of lines.slice(0, 20)) {
    const m = line.match(/^\*\*(Date|Plan|Result|Duration):\*\*\s*(.+?)\s*$/);
    if (m) meta[m[1].toLowerCase()] = m[2];
  }
  const sections = []; let current = null;
  for (const line of lines) {
    const h = line.match(/^###\s+(.+?)\s*$/);
    if (h) { if (current) sections.push(current); current = { title: h[1].trim(), body: [] }; }
    else if (current) { current.body.push(line); }
  }
  if (current) sections.push(current);

  const tests = sections.map((s) => {
    const bodyText = s.body.join('\n').trim();
    let status = 'broken';
    if (/^-\s*\[FAIL\]/m.test(bodyText)) status = 'failed';
    else if (/^-\s*\[PASS\]/m.test(bodyText)) status = 'passed';

    let statusDetails = undefined;
    if (status === 'failed') {
      const failLine = bodyText.split('\n').find(l => /^-\s*\[FAIL\]/.test(l));
      statusDetails = {
        message: failLine ? failLine.replace(/^-\s*\[FAIL\]\s*/, '').trim() : 'Test case marked FAIL',
        trace: bodyText.slice(0, 2000)
      };
    }
    return { title: s.title, body: bodyText, bodyHtml: mdToHtml(bodyText), status, statusDetails };
  });
  return { meta, tests };
}

function inferSuiteInfo(reportPath, meta) {
  const rel = path.relative(REPORTS_ROOT, reportPath);
  const parts = rel.split(/[\\/]/);
  const date = parts.length >= 2 ? parts[0] : 'unknown-date';
  const plan = path.basename(parts[parts.length - 1], '.md');
  let folder = 'general';
  if (meta && meta.plan) {
    const planParts = meta.plan.replace(/^test-plans\//, '').split(/[\\/]/);
    if (planParts.length >= 2) folder = planParts[0];
    else folder = path.basename(planParts[0], '.md');
  }
  return { date, plan, folder };
}

function parseReportStart(meta) {
  if (!meta.date) return Date.now();
  const m = meta.date.match(/(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}):(\d{2}))?/);
  if (!m) return Date.now();
  const t = Date.parse(`${m[1]}T${m[2] || '00'}:${m[3] || '00'}:00Z`);
  return Number.isNaN(t) ? Date.now() : t;
}

function parseDurationSec(durStr) {
  if (!durStr) return 0;
  const m = String(durStr).match(/(\d+(?:\.\d+)?)/);
  return m ? parseFloat(m[1]) : 0;
}

function buildAllureResults(reportPath) {
  const { meta, tests } = parseReport(reportPath);
  const { date, plan, folder } = inferSuiteInfo(reportPath, meta);
  const reportStart = parseReportStart(meta);
  const totalMs = parseDurationSec(meta.duration) * 1000 || Math.max(tests.length, 1) * 1000;
  const perTestMs = Math.max(Math.floor(totalMs / Math.max(tests.length, 1)), 500);

  tests.forEach((t, idx) => {
    const id = uuid();
    const start = reportStart + idx * perTestMs;
    const fullName = `test-plans/${folder}/${plan}.md#${t.title}`;
    const result = {
      uuid: id, historyId: hashId(fullName), testCaseId: hashId(fullName),
      name: t.title, fullName, status: t.status, statusDetails: t.statusDetails,
      stage: 'finished', start, stop: start + perTestMs,
      labels: [
        { name: 'parentSuite', value: folder },
        { name: 'suite', value: plan },
        { name: 'feature', value: folder },
        { name: 'story', value: plan },
        { name: 'package', value: `test-plans.${folder}` },
        { name: 'framework', value: 'markdown-driven' },
        { name: 'language', value: 'markdown' },
      ],
      description: t.body, descriptionHtml: t.bodyHtml,
      steps: [], attachments: [], parameters: [], links: [],
    };
    fs.writeFileSync(path.join(OUT_DIR, `${id}-result.json`), JSON.stringify(result, null, 2));
  });
  return tests.length;
}

function main() {
  const arg = process.argv[2];
  fs.mkdirSync(OUT_DIR, { recursive: true });
  let reports = [];
  if (arg && arg.endsWith('.md')) {
    const p = path.resolve(arg);
    if (fs.existsSync(p)) reports = [p];
  } else {
    if (fs.existsSync(REPORTS_ROOT)) {
      for (const d of fs.readdirSync(REPORTS_ROOT)) {
        const full = path.join(REPORTS_ROOT, d);
        if (fs.statSync(full).isDirectory())
          for (const f of fs.readdirSync(full))
            if (f.endsWith('.md')) reports.push(path.join(full, f));
      }
    }
  }
  let total = 0;
  for (const r of reports) { const n = buildAllureResults(r); total += n; console.log(`[allure] ${r}: ${n} test(s)`); }
  fs.writeFileSync(path.join(OUT_DIR, 'environment.properties'),
    `App=${APP_NAME}\nURL=${APP_URL}\nFramework=markdown-driven + Claude Code\n`);
  console.log(`[allure] Wrote ${total} test result(s) to ${OUT_DIR}`);
}
main();
