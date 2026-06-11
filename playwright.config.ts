import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: './.venv/bin/python -m uvicorn apps.api.app.main:app --app-dir . --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/healthz',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm --prefix apps/portal run dev -- --host 127.0.0.1 --port 4173',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})

