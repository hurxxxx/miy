import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test, type BrowserContext } from '@playwright/test';
import { buildAppHref } from '@miy/contracts/app-routes';
import { stubShellBackend } from './helpers';

const appOrigin = 'https://independent-app.example.test';
const appId = 'candidate-review';
const installationId = '00000000-1111-4222-8333-444444444444';
const hostPath = `/apps/${appId}/installed/${installationId}`;

test.use({ timezoneId: 'Asia/Seoul' });

test('registers a Workbench draft under the current login and recovers a lost registration response', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('The portal preview URL is required');
  await fixture(context, new URL(baseURL).origin);
  const sourceRevision = 'a'.repeat(40);
  const definition = {
    schema_version: 1,
    app_id: 'my-notes-draft',
    ownership: 'personal',
    sdk_version: 1,
    display: { name: '나만의 메모', translations: {}, icon: 'app-window' },
    source: {
      repository: 'https://code.example.test/my-notes.git',
      directory: '.',
    },
    entrypoints: { ui: '/', api: '/api', health: '/healthz' },
    runtime_profile: 'web-api-postgres-v1',
    requested_permissions: ['identity:read', 'data:read', 'data:write'],
  };
  const draft = {
    schema_version: 1,
    project_id: 'project-one',
    binding_version: 1,
    app_id: definition.app_id,
    source_revision: sourceRevision,
    source_manifest_digest: `sha256:${'1'.repeat(64)}`,
    definition_digest: `sha256:${'2'.repeat(64)}`,
    definition,
  };
  let posts = 0;
  let receipt: Record<string, unknown> | null = null;
  await context.route(
    '**/api/v1/independent-apps/bootstrap**',
    async (route) => {
      expect(route.request().headers().authorization).toBe(
        'Bearer e2e-test-token',
      );
      if (route.request().method() === 'POST') {
        posts++;
        const body = route.request().postDataJSON();
        expect(body.definition).toEqual(definition);
        expect(body.source_revision).toBe(sourceRevision);
        expect(body.granted_permissions).toEqual(['identity:read']);
        expect(body).not.toHaveProperty('enabled');
        receipt = {
          operation_id: body.operation_id,
          app_id: definition.app_id,
          installation_id: installationId,
          source_revision: sourceRevision,
          definition_digest: draft.definition_digest,
          created_at: new Date().toISOString(),
        };
        return route.abort('failed');
      }
      expect(receipt).not.toBeNull();
      return route.fulfill({ json: receipt });
    },
  );
  await page.goto('/');
  await page.getByRole('link', { name: '앱 등록', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '앱 등록', exact: true }),
  ).toBeVisible();
  await page.getByLabel('Workbench 등록 초안 파일').setInputFiles({
    name: 'miy-app-registration.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(draft)),
  });
  await expect(page.getByText('나만의 메모', { exact: true })).toBeVisible();
  await page
    .getByLabel('개발용 앱 주소')
    .fill('https://my-notes.dev.example.test');
  await page.getByLabel('내 프로필 읽기').check();
  await page.getByRole('button', { name: '앱 등록', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    '등록 응답을 확인하지 못했습니다',
  );
  expect(posts).toBe(1);
  const url = new URL(page.url());
  expect([...url.searchParams.keys()]).toEqual(['operation']);
  await page.getByRole('button', { name: '등록 결과 확인' }).click();
  await expect(
    page.getByRole('heading', { name: '앱 등록 기록을 확인했습니다.' }),
  ).toBeVisible();
  await expect(
    page.getByText('이 기록은 최초 등록 결과입니다.', { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: '앱 등록 기록을 확인했습니다.' }),
  ).toBeVisible();
  expect(posts).toBe(1);
});

async function fixture(
  context: BrowserContext,
  platformOrigin: string,
  uiContext = false,
  navigation = false,
  files = false,
) {
  // Every unmatched portal API remains synthetic; never fall through to a live API.
  await context.route(`${platformOrigin}/api/**`, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: 'Synthetic API not configured' },
    }),
  );
  await stubShellBackend(context, {
    enabledAppIds: files ? ['home', 'files'] : ['home'],
  });
  await context.route(
    '**/api/v1/personal-widgets/pms/tasks/assigned**',
    (route) =>
      route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } }),
  );
  let launchable = true;
  let launches = 0;
  let exchanges = 0;
  let failNextExchange = false;
  let challenge = '';
  const code = 'c'.repeat(43);
  await context.route('**/api/v1/independent-apps/catalog**', (route) =>
    route.fulfill({
      json: {
        page: 1,
        page_size: 200,
        total: 1,
        catalog_revision: String(launchable),
        items: [
          {
            definition: {
              definition: {
                app_id: appId,
                display: {
                  name: 'Candidate review',
                  translations: { 'ko-KR': '지원서 검토' },
                  icon: 'clipboard-check',
                },
                entrypoints: { ui: '/' },
              },
            },
            installations: [
              {
                id: installationId,
                app_id: appId,
                origin: appOrigin,
                environment: 'development',
                enabled: true,
                state: 'configured',
                generation: 1,
                launchable,
                ui_entrypoint: launchable ? '/' : null,
              },
            ],
          },
        ],
      },
    }),
  );
  await context.route('**/api/v1/independent-apps/launch', (route) => {
    expect(route.request().headers().authorization).toBe(
      'Bearer e2e-test-token',
    );
    const body = route.request().postDataJSON();
    expect(body.installation_id).toBe(installationId);
    challenge = body.code_challenge;
    launches += 1;
    return route.fulfill({
      json: {
        code,
        app_origin: appOrigin,
        expires_at: new Date(Date.now() + 60000).toISOString(),
      },
    });
  });
  let fileProofs = 0;
  let candidateReads = 0;
  let fileAuthorizations = 0;
  let contentReads = 0;
  let loseAuthorization = false;
  let denySelection = false;
  const file = {
    file_id: '12345678-1234-4234-8234-123456789012',
    // Core counts Unicode code points; exercise the real host/SDK at that limit.
    name:
      '선택용 합성 파일.txt' + '📄'.repeat(255 - '선택용 합성 파일.txt'.length),
    content_type: 'text/plain',
    size_bytes: 3,
    version: 'f'.repeat(64),
  };
  const selectionContext = (id: string) => ({
    schema_version: 1,
    installation_id: installationId,
    audience: appOrigin,
    selection_id: id,
  });
  await context.route(
    `${platformOrigin}/api/v1/independent-apps/_files/**`,
    async (route) => {
      expect(route.request().headers().authorization).toBe(
        'Bearer e2e-test-token',
      );
      expect(route.request().method()).toBe('POST');
      const body = route.request().postDataJSON();
      const path = new URL(route.request().url()).pathname;
      expect(body).toMatchObject({
        installation_id: installationId,
        audience: appOrigin,
        schema_version: 1,
        selection_request: 'synthetic-file-proof',
      });
      if (path.endsWith('/candidates')) {
        candidateReads++;
        expect(body.limit).toBe(25);
        return route.fulfill({
          json: {
            ...selectionContext(body.selection_id),
            items: [file],
            next_cursor: null,
            incomplete: false,
          },
        });
      }
      if (path.endsWith('/authorize-selection')) {
        fileAuthorizations++;
        expect(body.file_id).toBe(file.file_id);
        expect(body.expected_version).toBe(file.version);
        if (loseAuthorization) return route.abort('failed');
        return route.fulfill({
          json: {
            ...selectionContext(body.selection_id),
            file,
            read_grant: 'synthetic-file-read-grant',
            expires_at: new Date(Date.now() + 120000).toISOString(),
          },
        });
      }
      return route.fulfill({ status: 404 });
    },
  );
  const sdk = await readFile('packages/app-sdk/src/index.mjs', 'utf8');
  const fileSdk = await readFile(
    'packages/app-sdk/src/file-picker.mjs',
    'utf8',
  );
  await context.route(`${appOrigin}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/sdk.js')
      return route.fulfill({ contentType: 'text/javascript', body: sdk });
    if (path === '/file-picker.mjs')
      return route.fulfill({ contentType: 'text/javascript', body: fileSdk });
    if (path === '/api/platform-files/selection-request') {
      fileProofs++;
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers().authorization).toBe(
        `Bearer ${'t'.repeat(43)}`,
      );
      expect(route.request().headers().cookie).toBeUndefined();
      const body = route.request().postDataJSON();
      expect(Object.keys(body).sort()).toEqual([
        'schema_version',
        'selection_id',
      ]);
      if (denySelection)
        return route.fulfill({
          status: 403,
          json: { detail: 'Synthetic selection denied' },
        });
      return route.fulfill({
        json: {
          ...selectionContext(body.selection_id),
          selection_request: 'synthetic-file-proof',
          max_bytes: 10485760,
          expires_at: new Date(Date.now() + 60000).toISOString(),
        },
      });
    }
    if (path === '/api/platform-files/content') {
      contentReads++;
      expect(route.request().method()).toBe('GET');
      expect(new URL(route.request().url()).search).toBe('');
      expect(route.request().headers().authorization).toBe(
        `Bearer ${'t'.repeat(43)}`,
      );
      expect(route.request().headers()['x-miy-selected-file']).toBe(
        'synthetic-file-read-grant',
      );
      expect(route.request().headers().cookie).toBeUndefined();
      return route.fulfill({
        body: 'abc',
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': '3',
          'Cache-Control': 'private, no-store',
        },
      });
    }
    if (path === '/api/session/exchange') {
      const body = route.request().postDataJSON();
      expect(body.installation_id).toBe(installationId);
      expect(body.code).toBe(code);
      expect(
        createHash('sha256').update(body.code_verifier).digest('base64url'),
      ).toBe(challenge);
      expect(route.request().headers().authorization).toBeUndefined();
      expect(route.request().headers().cookie).toBeUndefined();
      exchanges += 1;
      if (failNextExchange) {
        failNextExchange = false;
        return route.fulfill({
          status: 401,
          json: { detail: 'Synthetic expired exchange' },
        });
      }
      return route.fulfill({
        json: {
          token: 't'.repeat(43),
          expires_at: new Date(Date.now() + 60000).toISOString(),
          installation_id: installationId,
          app_id: appId,
          environment: 'development',
          audience: appOrigin,
          permissions: files
            ? ['identity:read', 'files:read-selected']
            : ['identity:read'],
        },
      });
    }
    return route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><title>Independent app fixture</title>
      <h1>Independent application</h1><button id="connect">Connect</button><p id="status">Waiting</p><p id="ui-context">App defaults</p>
      <button id="offer" disabled>Offer Home</button><p id="offer-status">No offer</p>
      <button id="select-file" disabled>Select a file</button><button id="read-file" disabled>Read selected file</button><p id="file-status">No selection</p><p id="file-content">No bytes</p>
      <script type="module">
      import {connectApp} from '/sdk.js';
      const platformOrigin = ${JSON.stringify(platformOrigin)};
      const installationId = ${JSON.stringify(installationId)};
      let connection;
      let offerApp;
      let selectFile;
      let selectedFile;
      async function connect(hostWindow) {
        connection?.abort();
        connection = new AbortController();
        document.querySelector('#status').textContent = 'Connecting';
        const uiOptions = ${JSON.stringify(uiContext)} ? {
          signal: connection.signal,
          onUIContext: ({theme, locale}) => {
            document.documentElement.lang = locale;
            document.documentElement.style.colorScheme = theme;
            document.querySelector('#ui-context').textContent = theme + ' / ' + locale;
          },
        } : {};
        const navigationOptions = ${JSON.stringify(navigation)} ? {
          signal: connection.signal,
          onNavigationReady: (offer) => { offerApp = offer; document.querySelector('#offer').disabled = false; },
        } : {};
        const fileOptions = ${JSON.stringify(files)} ? {
          signal: connection.signal,
          onFilePickerReady: (capability) => { selectFile = capability.selectFile; document.querySelector('#select-file').disabled = false; },
        } : {};
        try { await connectApp({ platformOrigin, installationId, hostWindow, ...uiOptions, ...navigationOptions, ...fileOptions }); document.querySelector('#status').textContent = 'Connected to independent app'; }
        catch { document.querySelector('#status').textContent = 'Connection failed'; }
      }
      window.addEventListener('pagehide', () => connection?.abort());
      if (window.parent !== window) connect(window.parent);
      document.querySelector('#connect').onclick = () => connect(window.parent !== window ? window.parent : window.open(platformOrigin + ${JSON.stringify(hostPath + '?connect=popup')}, 'miy-login', 'popup,width=900,height=700'));
      document.querySelector('#offer').onclick = async () => {
        try { const result = await offerApp({appId:'home'}); document.querySelector('#offer-status').textContent = result.status; }
        catch { document.querySelector('#offer-status').textContent = 'unavailable'; }
      };
      document.querySelector('#select-file').onclick = async () => {
        document.querySelector('#file-status').textContent = 'Selecting';
        selectedFile = await selectFile();
        document.querySelector('#file-status').textContent = selectedFile.status;
        document.querySelector('#read-file').disabled = selectedFile.status !== 'selected';
      };
      document.querySelector('#read-file').onclick = async () => {
        try { document.querySelector('#file-content').textContent = new TextDecoder().decode(await selectedFile.read()); }
        catch { document.querySelector('#file-content').textContent = 'Read unavailable'; }
      };
      </script>`,
    });
  });
  return {
    revoke: () => {
      launchable = false;
    },
    counts: () => ({ launches, exchanges }),
    fileCounts: () => ({
      proofs: fileProofs,
      candidates: candidateReads,
      authorizations: fileAuthorizations,
      reads: contentReads,
    }),
    loseFileAuthorization: () => {
      loseAuthorization = true;
    },
    denyFileSelection: () => {
      denySelection = true;
    },
    failExchange: () => {
      failNextExchange = true;
    },
  };
}

test('discovers an arbitrary app and authenticates its isolated iframe without platform credentials or cookies', async ({
  page,
  context,
  baseURL,
}) => {
  const state = await fixture(context, new URL(baseURL!).origin);
  await page.goto('/');
  await page.getByRole('link', { name: '지원서 검토 개발 미리보기' }).click();
  await expect(page).toHaveURL(new RegExp(`${hostPath}$`));
  await expect(page).toHaveTitle('지원서 검토 | miy');
  const frame = page.frameLocator('iframe[title="지원서 검토"]');
  await expect(frame.getByText('Connected to independent app')).toBeVisible();
  expect(state.counts().exchanges).toBe(1);
  const appFrame = page
    .frames()
    .find((candidate) => candidate.url().startsWith(appOrigin))!;
  expect(
    await appFrame.evaluate(() => localStorage.getItem('miy.auth.token')),
  ).toBeNull();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  state.revoke();
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.locator('iframe')).toHaveCount(0);
  await expect(
    page
      .getByRole('alert')
      .filter({ hasText: '이 앱을 사용할 수 없거나 접근 권한이 없습니다.' }),
  ).toBeVisible();
});

test('reconnects the same iframe document after a failed exchange and another fresh handshake', async ({
  page,
  context,
  baseURL,
}) => {
  const state = await fixture(context, new URL(baseURL!).origin);
  state.failExchange();
  await page.goto(hostPath);
  const frame = page.frameLocator('iframe[title="지원서 검토"]');
  await expect(
    frame.getByText('Connection failed', { exact: true }),
  ).toBeVisible();
  const element = await frame.locator('#status').elementHandle();
  await frame.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(
    frame.getByText('Connected to independent app', { exact: true }),
  ).toBeVisible();
  expect(state.counts().exchanges).toBe(2);
  await frame.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect.poll(() => state.counts().exchanges).toBe(3);
  await expect(
    frame.getByText('Connected to independent app', { exact: true }),
  ).toBeVisible();
  expect(await element!.evaluate((node) => node.isConnected)).toBe(true);
});

test('authenticates the standalone app through its trusted platform popup', async ({
  page,
  context,
  baseURL,
}) => {
  const state = await fixture(context, new URL(baseURL!).origin);
  await page.goto(appOrigin);
  const popupReady = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  const popup = await popupReady;
  await expect.poll(() => popup.evaluate(() => !!window.opener)).toBe(true);
  await expect(popup).toHaveURL(new RegExp(`${hostPath}\\?connect=popup$`));
  await expect(page.getByText('Connected to independent app')).toBeVisible();
  await expect(
    popup.getByText('연결 정보를 전달했습니다. 원래 앱으로 돌아가세요.'),
  ).toBeVisible();
  expect(state.counts().exchanges).toBe(1);
  await popup.close();
});

test('updates an opted-in iframe theme and language without renewing its identity or replacing its document', async ({
  page,
  context,
  baseURL,
}) => {
  await page.emulateMedia({ colorScheme: 'light' });
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(context, new URL(baseURL).origin, true);
  await page.goto(hostPath);
  const frame = page.frameLocator('iframe');
  await expect(frame.locator('#status')).toHaveText(
    'Connected to independent app',
  );
  await expect(frame.locator('#ui-context')).toHaveText('light / ko-KR');
  const connectedCounts = state.counts();
  expect(connectedCounts.exchanges).toBe(1);
  const initialDocument = await frame.locator('#ui-context').elementHandle();
  if (!initialDocument)
    throw new Error('The connected app document is missing');

  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(frame.locator('#ui-context')).toHaveText('dark / ko-KR');
  await page.getByRole('button', { name: '내 설정', exact: true }).click();
  await page.getByRole('button', { name: '화면 설정', exact: true }).click();
  await page
    .getByRole('combobox', { name: '언어', exact: true })
    .selectOption('en-US');
  await expect(frame.locator('#ui-context')).toHaveText('dark / en-US');
  await expect(frame.locator('html')).toHaveAttribute('lang', 'en-US');
  await expect(frame.locator('html')).toHaveCSS('color-scheme', 'dark');
  expect(await initialDocument.evaluate((node) => node.isConnected)).toBe(true);
  expect(state.counts()).toEqual(connectedCounts);

  await page.keyboard.press('Escape');
  await page.goto('/');
  await page.goto(hostPath);
  await expect(frame.locator('#ui-context')).toHaveText('dark / en-US');
  await expect.poll(() => state.counts().exchanges).toBe(2);
});

test('updates standalone app appearance only through its live trusted popup and reconnects after closing it', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(context, new URL(baseURL).origin, true);
  await page.goto(appOrigin);
  await expect(page.locator('#ui-context')).toHaveText('App defaults');
  const opened = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  const popup = await opened;
  await popup.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('#ui-context')).toHaveText('light / ko-KR');
  await popup.getByRole('button', { name: '내 설정', exact: true }).click();
  await popup.getByRole('button', { name: '화면 설정', exact: true }).click();
  await popup.getByRole('button', { name: '다크', exact: true }).click();
  await popup
    .getByRole('combobox', { name: '언어', exact: true })
    .selectOption('en-US');
  await expect(page.locator('#ui-context')).toHaveText('dark / en-US');
  expect(state.counts()).toEqual({ launches: 1, exchanges: 1 });
  await popup.close();
  await expect(page.locator('#status')).toHaveText(
    'Connected to independent app',
  );
  await expect(page.locator('#ui-context')).toHaveText('dark / en-US');

  const reopened = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  const nextPopup = await reopened;
  await expect(page.locator('#status')).toHaveText(
    'Connected to independent app',
  );
  await expect(page.locator('#ui-context')).toHaveText('dark / en-US');
  await expect
    .poll(() => state.counts())
    .toEqual({ launches: 2, exchanges: 2 });
  expect(
    await page.evaluate(() => localStorage.getItem('miy.auth.token')),
  ).toBeNull();
  await nextPopup.close();
});

for (const popupMode of [false, true]) {
  test(`offers navigation only after a host click in ${popupMode ? 'popup' : 'iframe'} mode`, async ({
    page,
    context,
    baseURL,
  }) => {
    if (!baseURL) throw new Error('Browser test base URL is required');
    await fixture(context, new URL(baseURL).origin, false, true);
    let host = page;
    if (popupMode) {
      await page.goto(appOrigin);
      const opening = page.waitForEvent('popup');
      await page.getByRole('button', { name: 'Connect', exact: true }).click();
      host = await opening;
    } else await page.goto(hostPath);
    const app = popupMode ? page : page.frameLocator('iframe');
    await app.getByRole('button', { name: 'Offer Home' }).click();
    await expect(app.locator('#offer-status')).toHaveText('offered');
    await expect(host).toHaveURL(new RegExp(hostPath));
    await expect(
      host.getByRole('button', { name: '확인하고 이동' }),
    ).toBeVisible();
    await host.getByRole('button', { name: '확인하고 이동' }).click();
    await expect(host).toHaveURL(
      new URL(buildAppHref({ routeId: 'home.root' }), baseURL).href,
    );
    if (popupMode) {
      await expect(page).toHaveURL(`${appOrigin}/`);
      await host.close();
    }
  });
}

test('discards an offered move when current source admission is revoked before clicking', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(context, new URL(baseURL).origin, false, true);
  await page.goto(hostPath);
  const app = page.frameLocator('iframe');
  await app.getByRole('button', { name: 'Offer Home' }).click();
  await expect(app.locator('#offer-status')).toHaveText('offered');
  state.revoke();
  await page.getByRole('button', { name: '확인하고 이동' }).click();
  await expect(page.getByRole('button', { name: '확인하고 이동' })).toHaveCount(
    0,
  );
  await expect(page).toHaveURL(new RegExp(`${hostPath}$`));
});

test('selected-file iframe uses mobile keyboard confirmation and reads only after a separate app action', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(
    context,
    new URL(baseURL).origin,
    false,
    false,
    true,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(hostPath);
  const app = page.frameLocator('iframe');
  await app.getByRole('button', { name: 'Select a file', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '앱에 파일 선택해 주기' });
  await expect(dialog.getByRole('radio')).toHaveCount(1);
  await expect(
    dialog.getByRole('button', { name: '선택한 파일 읽기 허용', exact: true }),
  ).toBeDisabled();
  expect(state.fileCounts()).toEqual({
    proofs: 1,
    candidates: 1,
    authorizations: 0,
    reads: 0,
  });
  await dialog
    .getByRole('button', { name: '취소', exact: true })
    .last()
    .click();
  await expect(app.locator('#file-status')).toHaveText('canceled');
  await expect(dialog).toHaveCount(0);
  await app.getByRole('button', { name: 'Select a file', exact: true }).click();
  const radio = dialog.getByRole('radio', { name: /선택용 합성 파일.txt/ });
  await radio.focus();
  await radio.press('Space');
  const confirm = dialog.getByRole('button', {
    name: '선택한 파일 읽기 허용',
    exact: true,
  });
  await expect(confirm).toBeEnabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await confirm.focus();
  await confirm.press('Enter');
  await expect(app.locator('#file-status')).toHaveText('selected');
  await expect(app.locator('#file-content')).toHaveText('No bytes');
  expect(state.fileCounts()).toEqual({
    proofs: 2,
    candidates: 2,
    authorizations: 1,
    reads: 0,
  });
  await app.getByRole('button', { name: 'Read selected file' }).click();
  await expect(app.locator('#file-content')).toHaveText('abc');
  expect(state.fileCounts().reads).toBe(1);
});

test('selected-file lost authorization response stays unknown without automatic reissue', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(
    context,
    new URL(baseURL).origin,
    false,
    false,
    true,
  );
  state.loseFileAuthorization();
  await page.goto(hostPath);
  const app = page.frameLocator('iframe');
  await app.getByRole('button', { name: 'Select a file', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '앱에 파일 선택해 주기' });
  await dialog.getByRole('radio', { name: /선택용 합성 파일.txt/ }).check();
  const confirm = dialog.getByRole('button', {
    name: '선택한 파일 읽기 허용',
    exact: true,
  });
  await confirm.click();
  await expect(dialog.getByRole('alert')).toContainText(
    '이 요청을 다시 보내지 않습니다',
  );
  await expect(confirm).toBeDisabled();
  await expect(
    dialog.getByRole('button', { name: '검색', exact: true }),
  ).toBeDisabled();
  await page.keyboard.press('Enter');
  expect(state.fileCounts()).toEqual({
    proofs: 1,
    candidates: 1,
    authorizations: 1,
    reads: 0,
  });
  await expect(app.locator('#read-file')).toBeDisabled();
  await dialog
    .getByRole('button', { name: '취소', exact: true })
    .last()
    .click();
  await expect(app.locator('#file-status')).toHaveText('canceled');
  expect(state.fileCounts().authorizations).toBe(1);
});

test('selected-file current permission denial never opens the portal list or reads bytes', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(
    context,
    new URL(baseURL).origin,
    false,
    false,
    true,
  );
  await page.goto(hostPath);
  const app = page.frameLocator('iframe');
  await expect(app.locator('#status')).toHaveText(
    'Connected to independent app',
  );
  state.denyFileSelection();
  await app.getByRole('button', { name: 'Select a file', exact: true }).click();
  await expect(app.locator('#file-status')).toHaveText('unavailable');
  await expect(
    page.getByRole('dialog', { name: '앱에 파일 선택해 주기' }),
  ).toHaveCount(0);
  await expect(app.locator('#read-file')).toBeDisabled();
  expect(state.fileCounts()).toEqual({
    proofs: 1,
    candidates: 0,
    authorizations: 0,
    reads: 0,
  });
});

test('selected-file standalone popup confirms without moving the app and closed popup invalidates its read closure', async ({
  page,
  context,
  baseURL,
}) => {
  if (!baseURL) throw new Error('Browser test base URL is required');
  const state = await fixture(
    context,
    new URL(baseURL).origin,
    false,
    false,
    true,
  );
  await page.goto(appOrigin);
  const opening = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  const popup = await opening;
  await page
    .getByRole('button', { name: 'Select a file', exact: true })
    .click();
  const dialog = popup.getByRole('dialog', { name: '앱에 파일 선택해 주기' });
  await dialog.getByRole('radio', { name: /선택용 합성 파일.txt/ }).check();
  await dialog
    .getByRole('button', { name: '선택한 파일 읽기 허용', exact: true })
    .click();
  await expect(page.locator('#file-status')).toHaveText('selected');
  await expect(page).toHaveURL(`${appOrigin}/`);
  await popup.close();
  await page.getByRole('button', { name: 'Read selected file' }).click();
  await expect(page.locator('#file-content')).toHaveText('Read unavailable');
  expect(state.fileCounts()).toEqual({
    proofs: 1,
    candidates: 1,
    authorizations: 1,
    reads: 0,
  });
});
