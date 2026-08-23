import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const apiPort = process.env.PLAYWRIGHT_API_PORT ?? '8000'
const portalPort = process.env.PLAYWRIGHT_PORTAL_PORT ?? '4173'
const apiUrl = `http://127.0.0.1:${apiPort}`
const portalUrl = `http://127.0.0.1:${portalPort}`
const stateDir = process.env.NASUS_E2E_STATE_DIR ?? mkdtempSync(join(tmpdir(), `nasus-playwright-${apiPort}-`))
const databaseUrl = process.env.NASUS_E2E_DATABASE_URL ?? `sqlite+pysqlite:///${join(stateDir, 'nasus.db')}`
const adminToken = process.env.NASUS_E2E_ADMIN_TOKEN ?? 'nasus-e2e-platform-admin-token'

export default defineConfig({
  testDir: './tests/e2e',
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
