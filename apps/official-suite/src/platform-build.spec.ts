import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { expect, it, vi } from 'vitest';
import {
  CLIENT_BUILD_HEADER,
  CLIENT_BUILD_WEBSOCKET_QUERY_PARAM,
  installClientBuildFetchGuard,
  installClientBuildWebSocketGuard,
} from '@/src/platform/deployment/client-build-guard';
import { officialPlatformCompatibility } from '../vite/platform-compatibility.mts';

function compileCompatibility(buildId: string): {
  id: string;
  metadata: string;
} {
  // Native Vite/esbuild must run outside jsdom's Uint8Array realm. Build and
  // evaluate the actual owner entry rather than substituting a test constant.
  const script = `
import { build } from 'vite';
import { runInNewContext } from 'node:vm';
import { officialPlatformCompatibility } from './apps/official-suite/vite/platform-compatibility.mts';
const result = await build({
  configFile: false, root: 'apps/official-suite', logLevel: 'silent',
  plugins: [officialPlatformCompatibility(process.argv[1])],
  build: { write: false, minify: false,
    lib: { entry: 'src/platform-build.ts', formats: ['cjs'] } },
});
const outputs = result.flatMap(output => output.output);
const code = outputs.find(output => output.type === 'chunk');
const metadata = outputs.find(output => output.fileName === '.miy-platform-build-id');
if (!code || !metadata || metadata.type !== 'asset') throw new Error('Missing compatibility outputs');
const exports = {};
runInNewContext(code.code, { exports });
console.log(JSON.stringify({ id: exports.PLATFORM_COMPATIBILITY_BUILD_ID, metadata: metadata.source }));
`;
  return JSON.parse(
    execFileSync(
      process.execPath,
      [
        '--experimental-strip-types',
        '--input-type=module',
        '-e',
        script,
        buildId,
      ],
      { cwd: path.resolve(import.meta.dirname, '../../..'), encoding: 'utf8' },
    ),
  );
}

it('keeps old compiled JS on its paired ID when new server metadata arrives', async () => {
  const compiled = await compileCompatibility('reviewed-core-old');
  expect(compiled).toEqual({
    id: 'reviewed-core-old',
    metadata: 'reviewed-core-old\n',
  });
  const fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ platform_build_id: 'reviewed-core-new' })),
  );
  const socketUrls: string[] = [];
  class Socket extends EventTarget {
    constructor(url: string | URL) {
      super();
      socketUrls.push(String(url));
    }
  }
  const runtime = Object.assign(new EventTarget(), {
    fetch: fetch as typeof globalThis.fetch,
    location: {
      href: 'https://app.test/apps/docs',
      origin: 'https://app.test',
      replace: vi.fn(),
    },
    history: { state: null, replaceState: vi.fn() },
    sessionStorage: { getItem: vi.fn(), setItem: vi.fn() },
    WebSocket: Socket as unknown as typeof WebSocket,
  });
  const undoFetch = installClientBuildFetchGuard(runtime, {
    buildId: compiled.id,
  });
  const undoSocket = installClientBuildWebSocketGuard(runtime, {
    buildId: compiled.id,
  });
  try {
    // Read-only ops metadata may change; it cannot mutate an already compiled ID.
    expect(
      await (await runtime.fetch('/official-suite/platform-build.json')).json(),
    ).toEqual({ platform_build_id: 'reviewed-core-new' });
    await runtime.fetch('/api/v1/docs/native', { method: 'POST' });
    const [, options] = fetch.mock.calls[1] as unknown as [
      RequestInfo,
      RequestInit,
    ];
    expect(new Headers(options.headers).get(CLIENT_BUILD_HEADER)).toBe(
      'reviewed-core-old',
    );
    new runtime.WebSocket('wss://app.test/api/v1/docs/collab/pages/synthetic');
    expect(
      new URL(socketUrls[0]).searchParams.get(
        CLIENT_BUILD_WEBSOCKET_QUERY_PARAM,
      ),
    ).toBe('reviewed-core-old');
    expect(compiled.id).toBe('reviewed-core-old');
  } finally {
    undoSocket();
    undoFetch();
  }
});

it('retains the explicit no-build-ID contract and rejects invalid build inputs', async () => {
  expect(await compileCompatibility('')).toEqual({ id: '', metadata: '\n' });
  for (const buildId of ['../invalid', 'x'.repeat(129)])
    expect(() => officialPlatformCompatibility(buildId)).toThrow(
      'compatibility_invalid',
    );
});
