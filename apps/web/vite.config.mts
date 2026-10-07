/// <reference types='vitest' />
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { nxViteTsPaths } from '@nx/vite/plugins/nx-tsconfig-paths.plugin';
import { nxCopyAssetsPlugin } from '@nx/vite/plugins/nx-copy-assets.plugin';
import { officialFixedAssets } from '../../packages/official-suite-web/vite/fixed-assets.mjs';

const apiProxyTarget = process.env.MIY_WEB_API_PROXY_TARGET ?? 'http://127.0.0.1:8001';
const drawioProxyTarget =
  process.env.MIY_WEB_DRAWIO_PROXY_TARGET ??
  `http://127.0.0.1:${process.env.MIY_DRAWIO_PORT ?? 18082}`;
const codexConsoleProxyTarget = 'http://127.0.0.1:19367';
const webDevPort = Number(process.env.MIY_WEB_DEV_PORT ?? 4200);
const webDevAllowedHosts = (process.env.MIY_WEB_DEV_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean);
const webBuildOutDir = '../../dist/apps/web';
const drawioBrowserUrl =
  process.env.VITE_MIY_DRAWIO_URL ?? process.env.MIY_DRAWIO_SERVER_URL ?? '';
const drawioBrowserPort = String(process.env.MIY_DRAWIO_PORT ?? 18082);
const bentoBrowserUrl =
  process.env.VITE_MIY_BENTO_URL ?? process.env.MIY_BENTO_SERVER_URL ?? '';
const bentoBrowserPort = String(process.env.MIY_BENTO_PORT ?? 18084);
const apiProxyTimeoutMs = 0;
const drawioProxyTimeoutMs = 0;
const drawioProxyHeaders = {
  'X-Forwarded-Prefix': '/drawio',
};
const rewriteDrawioProxyPath = (requestPath: string) =>
  requestPath.replace(/^\/drawio(?=\/|$)/, '') || '/';

export default defineConfig(() => ({
  root: import.meta.dirname,
  cacheDir: '../../node_modules/.vite/apps/web',
  define: {
    __VUE_OPTIONS_API__: true,
    __VUE_PROD_DEVTOOLS__: false,
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false,
    'import.meta.env.VITE_MIY_DRAWIO_PORT': JSON.stringify(drawioBrowserPort),
    'import.meta.env.VITE_MIY_DRAWIO_URL': JSON.stringify(drawioBrowserUrl),
    'import.meta.env.VITE_MIY_BENTO_PORT': JSON.stringify(bentoBrowserPort),
    'import.meta.env.VITE_MIY_BENTO_URL': JSON.stringify(bentoBrowserUrl),
  },
  server: {
    port: webDevPort,
    strictPort: true,
    host: process.env.MIY_WEB_DEV_HOST ?? '127.0.0.1',
    allowedHosts: webDevAllowedHosts,
    proxy: {
      '/codex-console': {
        target: codexConsoleProxyTarget,
        timeout: 0,
        proxyTimeout: 0,
      },
      '/healthz': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
      },
      '/readyz': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
      },
      '/api': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
        ws: true,
      },
      '/drawio': {
        target: drawioProxyTarget,
        changeOrigin: true,
        headers: drawioProxyHeaders,
        timeout: drawioProxyTimeoutMs,
        proxyTimeout: drawioProxyTimeoutMs,
        rewrite: rewriteDrawioProxyPath,
      },
    },
  },
  preview: {
    port: webDevPort,
    strictPort: true,
    host: process.env.MIY_WEB_DEV_HOST ?? '127.0.0.1',
    allowedHosts: webDevAllowedHosts,
    proxy: {
      '/codex-console': {
        target: codexConsoleProxyTarget,
        timeout: 0,
        proxyTimeout: 0,
      },
      '/healthz': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
      },
      '/readyz': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
      },
      '/api': {
        target: apiProxyTarget,
        timeout: apiProxyTimeoutMs,
        proxyTimeout: apiProxyTimeoutMs,
        ws: true,
      },
      '/drawio': {
        target: drawioProxyTarget,
        changeOrigin: true,
        headers: drawioProxyHeaders,
        timeout: drawioProxyTimeoutMs,
        proxyTimeout: drawioProxyTimeoutMs,
        rewrite: rewriteDrawioProxyPath,
      },
    },
  },
  resolve: {
    alias: {
      '@miy/ui/styles.css': path.resolve(import.meta.dirname, '../../packages/ui/styles.css'),
      // These source-only libraries have no package exports. Keep dev resolution
      // explicit: Nx snapshots tsconfig paths when a long-running server starts.
      '@miy/official-suite-web': path.resolve(import.meta.dirname, '../../packages/official-suite-web/src'),
      '@miy/platform-web': path.resolve(import.meta.dirname, '../../packages/platform-web/src'),
      '@/src': path.resolve(import.meta.dirname, 'src'),
    },
  },
  plugins: [react(), tailwindcss(), nxViteTsPaths(), nxCopyAssetsPlugin(['*.md']), officialFixedAssets()],
  optimizeDeps: {
    include: ['@hyunbinseo/holidays-kr/all'],
  },
  // Uncomment this if you are using workers.
  // worker: {
  //   plugins: () => [ nxViteTsPaths() ],
  // },
  build: {
    outDir: webBuildOutDir,
    emptyOutDir: true,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 2200,
    commonjsOptions: {
      transformMixedEsModules: true,
    },
  },
  test: {
    name: 'web',
    watch: false,
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['{src,tests}/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}'],
    reporters: ['default'],
    coverage: {
      reportsDirectory: '../../coverage/apps/web',
      provider: 'v8' as const,
    },
  },
}));
