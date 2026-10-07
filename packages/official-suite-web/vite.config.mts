import { defineConfig } from 'vitest/config';
import { nxViteTsPaths } from '@nx/vite/plugins/nx-tsconfig-paths.plugin';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: import.meta.dirname,
  plugins: [nxViteTsPaths()],
  resolve: {
    alias: [
      {
        find: /^@miy\/ui$/,
        replacement: fileURLToPath(
          new URL('../ui/src/index.ts', import.meta.url),
        ),
      },
    ],
  },
  test: {
    name: 'official-suite-web',
    environment: 'jsdom',
    include: ['src/**/*.spec.{ts,tsx}'],
  },
});
