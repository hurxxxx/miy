import assert from 'node:assert/strict';
import {
  mkdir,
  mkdtemp,
  readFile,
  writeFile,
  copyFile,
  rm,
} from 'node:fs/promises';
import { createServer as httpServer } from 'node:http';
import path from 'node:path';
import { before, after, test } from 'node:test';
import { build, createServer, loadConfigFromFile } from 'vite';

const workspace = path.resolve(import.meta.dirname, '..');
const canonical = path.join(
  workspace,
  'packages/official-suite-web/public/recording-sync-sw.js',
);
const pluginName = 'miy-official-fixed-assets';
const fixedNames = ['recording-sync-sw.js', 'help/pms/user-guide.html'];
const fixedBytes = new Map();
let fixture;
let bytes;
let plugin;
let vite;
let http;
let origin;

async function assetPlugin(configPath) {
  const loaded = await loadConfigFromFile(
    { command: 'serve', mode: 'test' },
    configPath,
  );
  const plugins = loaded?.config.plugins
    .flat(Infinity)
    .filter((p) => p?.name === pluginName);
  assert.equal(
    plugins?.length,
    1,
    'The official composition must register one canonical asset owner',
  );
  return plugins[0];
}
async function serve(asset) {
  const server = await createServer({
    configFile: false,
    envFile: false,
    root: fixture,
    publicDir: false,
    appType: 'custom',
    logLevel: 'silent',
    plugins: [asset],
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, watch: null },
  });
  server.middlewares.use((_request, response) => {
    response.writeHead(404);
    response.end();
  });
  const listener = httpServer(server.middlewares);
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  return {
    server,
    listener,
    origin: `http://127.0.0.1:${listener.address().port}`,
  };
}
async function close(server, listener) {
  listener.closeAllConnections();
  await new Promise((resolve, reject) =>
    listener.close((error) => (error ? reject(error) : resolve())),
  );
  await server.close();
}
before(async () => {
  await mkdir(path.join(workspace, '.runtime'), { recursive: true });
  fixture = await mkdtemp(
    path.join(workspace, '.runtime/recording-sync-asset-test-'),
  );
  bytes = await readFile(canonical);
  for (const name of fixedNames)
    fixedBytes.set(
      name,
      await readFile(
        path.join(workspace, 'packages/official-suite-web/public', name),
      ),
    );
  const portal = await loadConfigFromFile(
    { command: 'serve', mode: 'test' },
    path.join(workspace, 'apps/web/vite.config.mts'),
  );
  assert.equal(
    portal.config.plugins
      .flat(Infinity)
      .filter((entry) => entry?.name === pluginName).length,
    0,
  );
  plugin = await assetPlugin(
    path.join(workspace, 'apps/official-suite/vite.config.mts'),
  );
  ({ server: vite, listener: http, origin } = await serve(plugin));
});
after(async () => {
  if (http) await close(vite, http);
  if (fixture) await rm(fixture, { recursive: true, force: true });
});

test(
  'serves canonical worker bytes and JavaScript MIME at the unchanged root URL',
  { timeout: 15000 },
  async () => {
    for (const suffix of ['', '?v=synthetic&path=../outside']) {
      const response = await fetch(origin + '/recording-sync-sw.js' + suffix);
      assert.equal(response.status, 200);
      assert.match(
        response.headers.get('content-type'),
        /^(?:text|application)\/javascript/,
      );
      assert.equal(
        response.headers.get('content-length'),
        String(bytes.length),
      );
      assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), bytes);
    }
  },
);
test(
  'HEAD has the same metadata without a body; unrelated paths and methods do not serve bytes',
  { timeout: 15000 },
  async () => {
    const response = await fetch(origin + '/recording-sync-sw.js?x=1', {
      method: 'HEAD',
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('content-length'), String(bytes.length));
    assert.equal((await response.arrayBuffer()).byteLength, 0);
    const invalid = await fetch(origin + '/recording-sync-sw.js', {
      method: 'POST',
    });
    assert.equal(invalid.status, 405);
    assert.equal(invalid.headers.get('allow'), 'GET, HEAD');
    assert.equal(await invalid.text(), '');
    for (const url of [
      '/nested/recording-sync-sw.js',
      '/recording-sync-sw.js/extra',
      '/recording-sync-sw%2ejs',
    ])
      assert.equal((await fetch(origin + url)).status, 404);
  },
);
test(
  'actual Vite fixture bundle emits the exact filename and bytes without an asset hash',
  { timeout: 15000 },
  async () => {
    const entry = path.join(fixture, 'entry.js');
    await writeFile(entry, 'export const synthetic = true;\n');
    const result = await build({
      configFile: false,
      envFile: false,
      root: fixture,
      publicDir: false,
      logLevel: 'silent',
      plugins: [plugin],
      build: { write: false, minify: false, rollupOptions: { input: entry } },
    });
    assert.ok(!Array.isArray(result) && 'output' in result);
    const assets = result.output.filter((output) => output.type === 'asset');
    assert.equal(assets.length, 2);
    for (const name of fixedNames) {
      const asset = assets.find((item) => item.fileName === name);
      assert.ok(asset);
      assert.deepEqual(Buffer.from(asset.source), fixedBytes.get(name));
    }
  },
);
test(
  'a missing canonical asset fails closed without a path disclosure or HTML fallback',
  { timeout: 15000 },
  async () => {
    // Load the exact adapter in an owned empty package fixture; never move/remove
    // the real canonical asset while another build or dev server could read it.
    await mkdir(path.join(fixture, 'vite'), { recursive: true });
    await copyFile(
      path.join(
        workspace,
        'packages/official-suite-web/vite/recording-sync-asset.mts',
      ),
      path.join(fixture, 'vite/recording-sync-asset.mts'),
    );
    await copyFile(
      path.join(workspace, 'packages/official-suite-web/vite/fixed-assets.mts'),
      path.join(fixture, 'vite/fixed-assets.mts'),
    );
    const config = path.join(fixture, 'config.mts');
    await writeFile(
      config,
      "import { recordingSyncAsset } from './vite/recording-sync-asset.mts';\nimport { officialFixedAssets } from './vite/fixed-assets.mts';\nif (recordingSyncAsset !== officialFixedAssets) throw new Error('factory identity changed');\nexport default { plugins: [recordingSyncAsset()] };\n",
    );
    const missing = await assetPlugin(config);
    const { server, listener, origin: missingOrigin } = await serve(missing);
    try {
      for (const name of fixedNames)
        for (const method of ['GET', 'HEAD']) {
          const response = await fetch(missingOrigin + '/' + name, {
            method,
          });
          assert.equal(response.status, 500);
          assert.equal(response.headers.get('cache-control'), 'no-store');
          assert.equal(
            await response.text(),
            method === 'HEAD' ? '' : 'Asset unavailable',
          );
        }
      await mkdir(path.join(fixture, 'public'), { recursive: true });
      await writeFile(path.join(fixture, 'public/recording-sync-sw.js'), bytes);
      // A present worker must not let a missing help document produce a partial build.
      await assert.rejects(
        build({
          configFile: false,
          envFile: false,
          root: fixture,
          publicDir: false,
          logLevel: 'silent',
          plugins: [missing],
          build: {
            write: false,
            rollupOptions: { input: path.join(fixture, 'entry.js') },
          },
        }),
      );
    } finally {
      await close(server, listener);
    }
  },
);

test(
  'serves only the canonical PMS help path with HTML MIME, query/HEAD parity and no method expansion',
  { timeout: 15000 },
  async () => {
    const name = 'help/pms/user-guide.html';
    const expected = fixedBytes.get(name);
    for (const suffix of ['', '?lang=en&path=../outside']) {
      const response = await fetch(origin + '/' + name + suffix);
      assert.equal(response.status, 200);
      assert.equal(
        response.headers.get('content-type'),
        'text/html; charset=utf-8',
      );
      assert.equal(
        response.headers.get('content-length'),
        String(expected.length),
      );
      assert.equal(response.headers.get('cache-control'), 'no-cache');
      assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), expected);
    }
    const head = await fetch(origin + '/' + name + '?lang=en', {
      method: 'HEAD',
    });
    assert.equal(head.status, 200);
    assert.equal(head.headers.get('content-type'), 'text/html; charset=utf-8');
    assert.equal(head.headers.get('content-length'), String(expected.length));
    assert.equal((await head.arrayBuffer()).byteLength, 0);
    const rejected = await fetch(origin + '/' + name, { method: 'POST' });
    assert.equal(rejected.status, 405);
    assert.equal(rejected.headers.get('allow'), 'GET, HEAD');
    assert.equal(await rejected.text(), '');
    for (const pathname of [
      '/help/pms/user-guide.html/extra',
      '/help/pms/user-guide%2ehtml',
      '/help/pms/other.html',
      '/help/pms',
    ]) {
      assert.equal((await fetch(origin + pathname)).status, 404);
    }
  },
);
