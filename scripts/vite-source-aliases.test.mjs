import path from 'node:path';
import assert from 'node:assert/strict';
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
