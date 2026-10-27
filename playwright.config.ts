import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const apiPort = process.env.PLAYWRIGHT_API_PORT ?? '8000'
const portalPort = process.env.PLAYWRIGHT_PORTAL_PORT ?? '4173'
const apiUrl = `http://127.0.0.1:${apiPort}`
const portalUrl = `http://127.0.0.1:${portalPort}`
const stateDir = process.env.NASUS_E2E_STATE_DIR ?? mkdtempSync(join(tmpdir(), `nasus-playwright-${apiPort}-`))
const databaseUrl = process.env.NASUS_E2E_DATABASE_URL
if (!databaseUrl || !/^postgresql(?:\+[a-z0-9_]+)?:\/\//.test(databaseUrl)) {
  throw new Error('Browser tests require isolated PostgreSQL. Use npm run test:e2e.')
}
if (!new URL(databaseUrl).pathname.startsWith('/nasus_test_')) {
  throw new Error('Browser tests must not write to a development or production database. Use npm run test:e2e.')
}
const adminToken = process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR ?? 'test-results',
  // Studio settings are shared by the test API; parallel theme writes race.
  workers: 1,
  use: {
    baseURL: portalUrl,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `./.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiUrl}/healthz`,
      reuseExistingServer: false,
      env: {
        ...process.env,
        NASUS_STATE_DIR: stateDir,
        NASUS_DATABASE_URL: databaseUrl,
        NASUS_AUTH_MODE: 'required',
        NASUS_AUTH_BEARER_TOKEN: adminToken,
        NASUS_AUTH_USER_ROLE: 'platform_admin',
        NASUS_SEED_DEMO_DATA: 'true',
        NASUS_RUNNER_MODE: 'protocol_stub',
      },
      timeout: 60_000,
    },
    {
      command: `npm --prefix apps/portal run dev -- --host 127.0.0.1 --port ${portalPort}`,
      url: portalUrl,
      reuseExistingServer: false,
      env: {
        ...process.env,
        NASUS_PORTAL_API_PROXY: apiUrl,
      },
      timeout: 60_000,
    },
  ],
})
