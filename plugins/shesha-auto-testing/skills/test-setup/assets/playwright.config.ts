import { defineConfig, devices } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// Load credentials/config from a gitignored .env into process.env, with zero
// dependencies. Real environment variables (e.g. CI secrets) always win — we
// only fill in keys that aren't already set. Copy .env.example → .env locally.
const envPath = resolve(__dirname, '.env');
if (existsSync(envPath)) {
  for (const rawLine of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (key && process.env[key] === undefined) process.env[key] = val;
  }
}

// Resolve the site under test. Precedence: explicit APP_URL, then the URL for the
// active TEST_ENV (e.g. TEST_ENV=qa → QA_APP_URL). Specs use relative paths, so
// switching TEST_ENV re-points every test. Left undefined if nothing is set —
// Playwright then requires absolute URLs and the spec throws a clear error.
function resolveBaseURL(): string | undefined {
  if (process.env.APP_URL) return process.env.APP_URL;
  const env = process.env.TEST_ENV?.toUpperCase();
  if (env && process.env[`${env}_APP_URL`]) return process.env[`${env}_APP_URL`];
  return undefined;
}

export default defineConfig({
  testDir: './test-plans',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['json', { outputFile: 'test-results/results.json' }],
    ['junit', { outputFile: 'test-results/junit.xml' }],
  ],
  use: {
    baseURL: resolveBaseURL(),
    headless: process.env.HEADED === '1' ? false : true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  outputDir: 'test-results/artifacts',
});
