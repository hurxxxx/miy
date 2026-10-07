import { defineConfig } from '@playwright/test';
import base from './playwright.config';

if (!base.webServer || Array.isArray(base.webServer))
  throw new Error('Expected the single disposable Workbench browser server');

export default defineConfig({
  ...base,
  testMatch: '**/registration.authorization.ts',
  webServer: {
    ...base.webServer,
    command:
      'uv run --frozen --directory ../codex-console-api --group dev python tests/browser_registration_server.py',
  },
});
