import path from 'node:path';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  copyFile,
  mkdir,
  mkdtemp,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { before, after, test } from 'node:test';
import { createServer, loadConfigFromFile } from 'vite';

const workspace = path.resolve(import.meta.dirname, '..');
const entries = [
  '@miy/official-suite-web',
  '@miy/official-suite-web/diagrams',
  '@miy/official-suite-web/diagrams/module',
  '@miy/official-suite-web/bento',
  '@miy/official-suite-web/bento/module',
  '@miy/official-suite-web/mail',
  '@miy/official-suite-web/mail/module',
  '@miy/official-suite-web/planner/module',
  '@miy/official-suite-web/planner/public-api',
  '@miy/official-suite-web/planner/messages',
  '@miy/official-suite-web/calendar/calendar-events-session',
  '@miy/official-suite-web/calendar/calendar-api',
  '@miy/official-suite-web/calendar/use-calendar-events',
  '@miy/official-suite-web/calendar/calendar-events-changed',
  '@miy/official-suite-web/calendar/calendar-types',
  '@miy/official-suite-web/calendar/UnifiedCalendar',
  '@miy/official-suite-web/calendar/fullcalendar-theme.css',
  '@miy/official-suite-web/calendar/unified-calendar-adapter',
  '@miy/platform-web/time/korean-holidays',
  '@miy/platform-web/theme/app-color-fallbacks',
  '@miy/platform-web/personal-widgets/floating-panel-events',
  '@miy/official-suite-web/planner',
  '@miy/official-suite-web/pms/module',
  '@miy/official-suite-web/pms/messages',
  '@miy/platform-web/routing/shell-navigation-model',
  '@miy/official-suite-web/pms',
  '@miy/official-suite-web/meeting/module',
  '@miy/official-suite-web/meeting/public-api',
  '@miy/official-suite-web/meeting/messages',
  '@miy/platform-web/form/FormDialog',
  '@miy/platform-web/users/remote-user-search-session',
  '@miy/platform-web/ai/ai-api',
  '@miy/platform-web/ai/conversations-api',
  '@miy/platform-web/ai/hermes-agent-api',
  '@miy/official-suite-web/meeting',
  '@miy/platform-web/chatbot',
  '@miy/platform-web/chatbot/module',
  '@miy/platform-web/chatbot/manifest',
  '@miy/platform-web/chatbot/state-types',
  '@miy/platform-web/chatbot/messages',
  '@miy/platform-web/ai/hermes-terminal-api',
  '@miy/platform-web/network/sse-parser',
  '@miy/platform-web/ai/artifacts/MarkdownContent',
  '@miy/platform-web/ai/artifacts/DocumentArtifact',
  '@miy/official-suite-web/files/module',
  '@miy/official-suite-web/files/messages',
  '@miy/official-suite-web/video-chat/module',
  '@miy/official-suite-web/video-chat/messages',
  '@miy/official-suite-web/video-chat',
  '@miy/official-suite-web/files',
  '@miy/official-suite-web/recording',
  '@miy/official-suite-web/recording/module',
  '@miy/official-suite-web/recording/messages',
  '@miy/platform-web/apps/app-links',
  '@miy/platform-web/network/request-concurrency',
  '@miy/official-suite-web/docs',
  '@miy/official-suite-web/docs/module',
  '@miy/official-suite-web/docs/messages',
  '@miy/official-suite-web/community',
  '@miy/official-suite-web/community/module',
  '@miy/official-suite-web/community/editor',
  '@miy/official-suite-web/community/events',
  '@miy/official-suite-web/community/messages',
  '@miy/official-suite-web/whiteboard',
  '@miy/official-suite-web/whiteboard/module',
  '@miy/official-suite-web/manifests/pms',
  '@miy/platform-web',
  '@miy/platform-web/auth-context',
  '@miy/platform-web/auth-api',
  '@miy/platform-web/i18n',
  '@miy/platform-web/i18n/resources',
  '@miy/platform-web/date/UserDateTime',
  '@miy/platform-web/api-client',
  '@miy/platform-web/date/DateInput',
  '@miy/platform-web/time/time-utils',
  '@miy/platform-web/time/native-date-input',
  '@miy/platform-web/apps',
  '@miy/platform-web/pickers',
  '@miy/platform-web/ordering',
  '@miy/platform-web/browser',
  '@miy/platform-web/format',
  '@miy/platform-web/media',
  '@miy/platform-web/routing',
  '@miy/platform-web/deployment',
  '@miy/platform-web/realtime',
  '@miy/platform-web/directory',
  '@miy/platform-web/users',
];
let server;
before(async () => {
  const environment = { command: 'serve', mode: 'test' };
  const web = await loadConfigFromFile(
    environment,
    path.join(workspace, 'apps/web/vite.config.mts'),
  );
  const suite = await loadConfigFromFile(
    environment,
    path.join(workspace, 'apps/official-suite/vite.config.mts'),
  );
  assert.ok(web);
  assert.ok(suite);
  assert.deepEqual(suite.config.resolve.alias, web.config.resolve.alias);
  // Exercise actual Vite resolution without Nx's startup-only tsconfig cache.
  // No listener, HMR socket, filesystem watcher, optimizer crawl or .env read.
  server = await createServer({
    configFile: false,
    envFile: false,
    root: workspace,
    logLevel: 'silent',
    resolve: web.config.resolve,
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, watch: null },
  });
});
after(async () => server?.close());
test('first-party API proxies use the configured listener in both native Vite factories', async () => {
  const sandbox = await mkdtemp(path.join(tmpdir(), 'miy-vite-first-party-'));
  try {
    for (const name of [
      'apps/web/vite.config.mts',
      'apps/official-suite/vite.config.mts',
      'apps/official-suite/vite/platform-compatibility.mts',
      'packages/official-suite-web/vite/ui-routing.mts',
      'packages/official-suite-web/vite/platform-ui-boundary.mts',
      'packages/official-suite-web/vite/fixed-assets.mts',
      'packages/contracts/app-contracts.json',
      'scripts/development-listener.mjs',
    ]) {
      const target = path.join(sandbox, name);
      await mkdir(path.dirname(target), { recursive: true });
      await copyFile(path.join(workspace, name), target);
    }
    await symlink(
      path.join(workspace, 'node_modules'),
      path.join(sandbox, 'node_modules'),
      'dir',
    );
    await writeFile(path.join(sandbox, 'package.json'), '{"type":"module"}\n');
    await mkdir(path.join(sandbox, '.runtime'));
    await writeFile(
      path.join(sandbox, '.runtime/first-party-api-routes.json'),
      JSON.stringify({
        api_prefix: '/api/v1',
        official_patterns: [
          '^/api/v1/docs/items/[0-9]+$',
          '^/api/v1/docs/collab/pages/[0-9]+$',
        ],
      }),
    );
    const result = spawnSync(process.execPath, ['--input-type=module', '-'], {
      cwd: sandbox,
      encoding: 'utf8',
      env: { PATH: process.env.PATH, NODE_ENV: 'test' },
      timeout: 30_000,
      input: `
import assert from 'node:assert/strict';
import path from 'node:path';
import { loadConfigFromFile } from 'vite';
const environment = { command: 'serve', mode: 'first-party' };
const configs = ['apps/web/vite.config.mts', 'apps/official-suite/vite.config.mts'];
const commonTarget = 'http://192.0.2.15:9007';
process.env.MIY_WEB_API_PROXY_TARGET = commonTarget;
const hosts = [
  [undefined, 'http://127.0.0.1:18781'],
  ['127.0.0.1', 'http://127.0.0.1:18781'],
  ['192.0.2.10', 'http://192.0.2.10:18781'],
  ['0.0.0.0', 'http://127.0.0.1:18781'],
  ['::', 'http://[::1]:18781'],
  ['::1', 'http://[::1]:18781'],
  ['2001:db8::5', 'http://[2001:db8::5]:18781'],
  ['dev.example.com', 'http://dev.example.com:18781'],
];
for (const [host, expected] of hosts) {
  if (host === undefined) delete process.env.MIY_DEV_API_HOST;
  else process.env.MIY_DEV_API_HOST = host;
  for (const name of configs) {
    const loaded = await loadConfigFromFile(environment, path.resolve(name));
    for (const section of ['server', 'preview']) {
      const proxy = loaded.config[section].proxy;
      assert.equal(proxy['/api'].target, commonTarget);
      assert.equal(proxy['/api'].ws, true);
      const officialKeys = Object.keys(proxy).filter(key => key.startsWith('^/api/v1/docs/'));
      assert.equal(officialKeys.length, 2);
      for (const key of officialKeys) {
        assert.equal(proxy[key].target, expected);
        assert.equal(proxy[key].ws, true);
        assert.equal(proxy[key].timeout, 0);
        assert.equal(proxy[key].proxyTimeout, 0);
      }
      const key = officialKeys.find(key => new RegExp(key).test('/api/v1/docs/items/7?version=2'));
      assert.ok(key);
      assert.equal(proxy[key].target, expected);
      assert.ok(officialKeys.some(key => new RegExp(key).test('/api/v1/docs/collab/pages/7')));
    }
  }
}
for (const host of ['', 'http://host', 'user@host', 'host/path', 'host?key=x']) {
  process.env.MIY_DEV_API_HOST = host;
  for (const name of configs)
    await assert.rejects(loadConfigFromFile(environment, path.resolve(name)), /development listener host/);
}
console.log('native routing listeners8/configs2/sections2/invalid5: PASS');
`,
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(
      result.stdout.trim(),
      'native routing listeners8/configs2/sections2/invalid5: PASS',
    );
  } finally {
    await rm(sandbox, { recursive: true, force: true });
  }
});
for (const entry of entries) {
  test(`resolves ${entry} without a package symlink or Nx plugin`, async () => {
    const resolved = await server.pluginContainer.resolveId(
      entry,
      path.join(workspace, 'apps/web/src/app/AppRoot.tsx'),
    );
    const owner = entry.startsWith('@miy/official-suite-web')
      ? 'official-suite-web'
      : 'platform-web';
    assert.ok(
      resolved?.id.startsWith(
        path.join(workspace, 'packages', owner, 'src') + path.sep,
      ),
    );
  });
}
for (const entry of [
  '@miy/official-suite-web-other',
  '@miy/platform-web-other',
]) {
  test(`does not resolve unrelated package ${entry}`, async () => {
    assert.equal(await server.pluginContainer.resolveId(entry), null);
  });
}
