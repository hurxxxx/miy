import path from 'node:path';
import { defineConfig, type ViteUserConfig } from 'vitest/config';
import legacyWebConfig from '../web/vite.config.mts';
import { officialFixedAssets } from '../../packages/official-suite-web/vite/fixed-assets.mts';
import { officialUiProxyKeys } from '../../packages/official-suite-web/vite/ui-routing.mts';
import type { Plugin, ProxyOptions } from 'vite';

const withoutSelfProxy = (
  proxy: Record<string, string | ProxyOptions> | undefined,
) =>
  Object.fromEntries(
    Object.entries(proxy ?? {}).filter(
      ([key]) => !officialUiProxyKeys.includes(key),
    ),
  );
const developmentCompatibility: Plugin = {
  name: 'miy-official-development-compatibility',
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      const path = request.url?.split('?', 1)[0];
      if (
        path !== '/official-suite/platform-build.json' &&
        path !== '/platform-build.json'
      )
        return next();
      response.writeHead(200, {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
      });
      response.end(JSON.stringify({ platform_build_id: null }));
    });
  },
};

// Toolchain/common SDK reuse does not make the platform artifact compile official screens.
export default defineConfig(async (environment) => {
  const shared: ViteUserConfig =
    typeof legacyWebConfig === 'function'
      ? await legacyWebConfig(environment)
      : await legacyWebConfig;
  return {
    ...shared,
    base: '/official-suite/',
    root: import.meta.dirname,
    publicDir: path.resolve(import.meta.dirname, '../web/public'),
    cacheDir: '../../node_modules/.vite/apps/official-suite',
    server: {
      ...shared.server,
      port: 4201,
      proxy: withoutSelfProxy(shared.server?.proxy),
    },
    preview: {
      ...shared.preview,
      port: 4201,
      proxy: withoutSelfProxy(shared.preview?.proxy),
    },
    plugins: [
      ...(shared.plugins ?? []).filter(
        (plugin) =>
          !plugin ||
          !('name' in plugin) ||
          plugin.name !== 'miy-platform-ui-boundary',
      ),
      officialFixedAssets(),
      developmentCompatibility,
    ],
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
