import { defineConfig, devices } from '@playwright/test';

const PORT = 8765;
const PREVIEW_PORT = 8766;
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: BASE },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'narrow', use: { ...devices['Desktop Chrome'], viewport: { width: 320, height: 640 } } },
  ],
  webServer: [
    {
      command: 'uv run python tests/e2e/serve.py',
      url: `${BASE}/api/catalogue`,
      env: { FDSTOOLKIT_E2E_PORT: String(PORT) },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `pnpm exec vite preview --config vite.config.mjs --host 127.0.0.1 --port ${PREVIEW_PORT} --strictPort`,
      url: `http://127.0.0.1:${PREVIEW_PORT}/static/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
