import path from 'node:path';
import { defineConfig, type ViteUserConfig } from 'vitest/config';
import legacyWebConfig from '../web/vite.config.mts';

// Share the existing UI toolchain/proxy configuration during the source-boundary stage.
// This bridge is not a separate API, authentication protocol, or deployment unit.
export default defineConfig(async (environment) => {
  const shared: ViteUserConfig =
    typeof legacyWebConfig === 'function'
      ? await legacyWebConfig(environment)
      : await legacyWebConfig;
  return {
    ...shared,
    root: import.meta.dirname,
    publicDir: path.resolve(import.meta.dirname, '../web/public'),
    cacheDir: '../../node_modules/.vite/apps/official-suite',
    server: { ...shared.server, port: 4201 },
    preview: { ...shared.preview, port: 4201 },
    build: { ...shared.build, outDir: '../../dist/apps/official-suite' },
    test: {
      ...shared.test,
      name: 'official-suite',
      setupFiles: [
        path.resolve(import.meta.dirname, '../web/src/test-setup.ts'),
      ],
      coverage: { reportsDirectory: '../../coverage/apps/official-suite' },
    },
  };
});
