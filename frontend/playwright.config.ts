import { defineConfig, devices } from '@playwright/test';
import * as os from 'os';
import * as path from 'path';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'on-first-retry',
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'python ../start.py --no-browser',
    url: 'http://127.0.0.1:8765/',
    reuseExistingServer: false,
    timeout: 30000,
    env: {
      PHOTO_PRIVATEER_DATA_DIR: process.env.PHOTO_PRIVATEER_DATA_DIR || path.join(os.tmpdir(), 'photo_privateer_playwright_' + Date.now()),
      PHOTO_PRIVATEER_TEST_MODE: '1',
      PHOTO_PRIVATEER_HOST: '127.0.0.1',
      PHOTO_PRIVATEER_PORT: '8765',
      GOOGLE_APPLICATION_CREDENTIALS: '',
    },
  },
});
