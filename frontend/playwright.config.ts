import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: process.env.PARASITE_E2E_BASE_URL ? 'live-workbench.spec.ts' : 'workbench.spec.ts',
  fullyParallel: false,
  reporter: 'list',
  use: { baseURL: process.env.PARASITE_E2E_BASE_URL || 'http://127.0.0.1:5173', channel: process.env.CI ? undefined : 'chrome', trace: 'retain-on-failure' },
  webServer: process.env.PARASITE_E2E_BASE_URL ? undefined : { command: 'npm run preview -- --port 5173 --strictPort', url: 'http://127.0.0.1:5173', reuseExistingServer: false, timeout: 30000 },
});
