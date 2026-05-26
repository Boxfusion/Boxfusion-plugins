#!/usr/bin/env node
/**
 * Playwright-first test runner for markdown-driven plans.
 *
 * Flow (called by the run-test skill):
 *   1. Resolve <plan>.md → paired <plan>.spec.ts beside it.
 *   2. If the spec is missing, emit { status: "no-spec" } so Claude scaffolds it.
 *   3. Run `npx playwright test <spec>`; parse test-results/results.json.
 *   4. Write test-reports/<today>/<plan-name>.md in the RULES.md §4 format.
 *   5. Emit a JSON summary to stdout describing each test (incl. failure location)
 *      so the skill can drive AI-repair on just the failing test/step.
 *
 * Usage:
 *   node scripts/run-plan.js <plan.md>                 # full run + report
 *   node scripts/run-plan.js <plan.md> --check          # exit 0 if spec exists, else "no-spec"
 *   node scripts/run-plan.js <plan.md> --grep "TC-02"   # single test (for post-repair re-run)
 *   node scripts/run-plan.js <plan.md> --no-report      # skip writing the .md report (re-run mode)
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const REPO_ROOT = path.resolve(__dirname, '..');
const REPORTS_ROOT = path.join(REPO_ROOT, 'test-reports');
const RESULTS_JSON = path.join(REPO_ROOT, 'test-results', 'results.json');

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function utcStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

function emit(payload) {
  process.stdout.write(JSON.stringify(payload, null, 2) + '\n');
}

function fail(msg, extra = {}) {
  emit({ status: 'error', error: msg, ...extra });
  process.exit(2);
}

function resolveSpec(planPath) {
  const abs = path.resolve(planPath);
  if (!fs.existsSync(abs)) fail(`Plan not found: ${planPath}`);
  if (!abs.endsWith('.md')) fail(`Plan must be a .md file: ${planPath}`);
  return abs.replace(/\.md$/, '.spec.ts');
}

function parseArgs(argv) {
  const opts = { plan: null, check: false, grep: null, noReport: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--check') opts.check = true;
    else if (a === '--no-report') opts.noReport = true;
    else if (a === '--grep') opts.grep = argv[++i];
    else if (!opts.plan) opts.plan = a;
  }
  if (!opts.plan) fail('Usage: run-plan.js <plan.md> [--check] [--grep <pattern>] [--no-report]');
  return opts;
}

function runPlaywright(specPath, grep) {
  // Playwright treats positional args as regexes against file paths.
  // On Windows, an absolute path with backslashes and a drive colon never matches,
  // so pass a forward-slash path relative to the repo root.
  const specArg = path.relative(REPO_ROOT, specPath).replace(/\\/g, '/');
  const args = ['playwright', 'test', specArg, '--reporter=json,list'];
  if (grep) { args.push('-g', grep); }
  // wipe previous json so a crash doesn't leave a stale file
  if (fs.existsSync(RESULTS_JSON)) fs.unlinkSync(RESULTS_JSON);
  const res = spawnSync('npx', args, {
    cwd: REPO_ROOT,
    stdio: ['ignore', 'inherit', 'inherit'],
    shell: process.platform === 'win32',
    env: { ...process.env, PLAYWRIGHT_JSON_OUTPUT_NAME: RESULTS_JSON },
  });
  return { exitCode: res.status ?? 1 };
}

function flattenSuites(suites, acc = []) {
  for (const s of suites || []) {
    if (Array.isArray(s.specs)) {
      for (const spec of s.specs) {
        for (const test of spec.tests || []) {
          for (const result of test.results || []) {
            acc.push({ title: spec.title, file: spec.file, line: spec.line, result });
          }
        }
      }
    }
    if (Array.isArray(s.suites)) flattenSuites(s.suites, acc);
  }
  return acc;
}

function summariseResults() {
  if (!fs.existsSync(RESULTS_JSON)) {
    return { tests: [], passed: 0, failed: 0, duration: 0, totalAssertions: 0 };
  }
  const raw = JSON.parse(fs.readFileSync(RESULTS_JSON, 'utf8'));
  const flat = flattenSuites(raw.suites || []);
  const tests = flat.map(({ title, file, line, result }) => {
    const failed = result.status !== 'passed';
    const firstError = (result.errors && result.errors[0]) || result.error;
    return {
      title,
      file: file ? path.relative(REPO_ROOT, file).replace(/\\/g, '/') : null,
      specLine: line,
      status: result.status,
      durationMs: result.duration ?? 0,
      error: failed && firstError ? {
        message: firstError.message || String(firstError),
        stack: firstError.stack,
        location: firstError.location || null,
        snippet: firstError.snippet || null,
      } : null,
    };
  });
  return {
    tests,
    passed: tests.filter(t => t.status === 'passed').length,
    failed: tests.filter(t => t.status !== 'passed').length,
    duration: (raw.stats?.duration ?? tests.reduce((a, t) => a + t.durationMs, 0)) / 1000,
  };
}

function classifyOverall({ passed, failed }) {
  if (failed === 0 && passed > 0) return 'PASSED';
  const total = passed + failed;
  if (total === 0) return 'FAILED';
  if (failed / total > 0.5) return 'FAILED';
  return 'PARTIAL';
}

function planTitle(planPath) {
  const raw = fs.readFileSync(planPath, 'utf8');
  const m = raw.match(/^#\s+(.+)$/m);
  return m ? m[1].trim() : path.basename(planPath, '.md');
}

function writeReport({ planPath, specPath, summary, overall, executionMode }) {
  const day = todayStr();
  const dir = path.join(REPORTS_ROOT, day);
  fs.mkdirSync(dir, { recursive: true });
  const name = path.basename(planPath, '.md');
  const reportPath = path.join(dir, `${name}.md`);
  const planRel = path.relative(REPO_ROOT, planPath).replace(/\\/g, '/');
  const specRel = path.relative(REPO_ROOT, specPath).replace(/\\/g, '/');

  const lines = [];
  lines.push(`# Report: ${planTitle(planPath)}`);
  lines.push(`**Date:** ${utcStamp()}`);
  lines.push(`**Plan:** ${planRel}`);
  lines.push(`**Spec:** ${specRel}`);
  lines.push(`**Execution Mode:** ${executionMode}`);
  lines.push(`**Result:** ${overall}`);
  lines.push(`**Duration:** ${summary.duration.toFixed(1)}s`);
  lines.push('');
  lines.push('## Summary');
  lines.push('| Total Steps | Passed | Failed | Skipped |');
  lines.push('|-------------|--------|--------|---------|');
  const total = summary.passed + summary.failed;
  lines.push(`| ${total} | ${summary.passed} | ${summary.failed} | 0 |`);
  lines.push('');
  lines.push('## Step Results');
  for (const t of summary.tests) {
    const ok = t.status === 'passed';
    lines.push(`### ${t.title}`);
    lines.push(`**Mode:** ${t.repairedBy ? `ai-repair (patched ${t.repairedBy})` : 'playwright-script'}`);
    lines.push(`**Duration:** ${(t.durationMs / 1000).toFixed(1)}s`);
    lines.push(`- [${ok ? 'PASS' : 'FAIL'}] ${t.title}`);
    if (!ok && t.error) {
      lines.push('');
      lines.push('**Error:**');
      lines.push('```');
      lines.push(String(t.error.message).slice(0, 1500));
      lines.push('```');
      if (t.error.location) {
        lines.push(`**Location:** ${t.error.location.file}:${t.error.location.line}:${t.error.location.column}`);
      }
    }
    lines.push('');
  }
  fs.writeFileSync(reportPath, lines.join('\n'));
  return reportPath;
}

function main() {
  const opts = parseArgs(process.argv);
  const planPath = path.resolve(opts.plan);
  const specPath = resolveSpec(planPath);

  if (opts.check) {
    emit({ status: fs.existsSync(specPath) ? 'spec-exists' : 'no-spec', planPath, specPath });
    return;
  }
  if (!fs.existsSync(specPath)) {
    emit({ status: 'no-spec', planPath, specPath });
    return;
  }

  runPlaywright(specPath, opts.grep);
  const summary = summariseResults();
  const overall = classifyOverall(summary);
  const executionMode = summary.failed === 0 ? 'playwright-script' : 'playwright-script (failures pending AI-repair)';

  let reportPath = null;
  if (!opts.noReport) {
    reportPath = writeReport({ planPath, specPath, summary, overall, executionMode });
  }

  emit({
    status: overall.toLowerCase(),
    planPath: path.relative(REPO_ROOT, planPath).replace(/\\/g, '/'),
    specPath: path.relative(REPO_ROOT, specPath).replace(/\\/g, '/'),
    reportPath: reportPath ? path.relative(REPO_ROOT, reportPath).replace(/\\/g, '/') : null,
    duration: summary.duration,
    tests: summary.tests,
  });
}

main();
