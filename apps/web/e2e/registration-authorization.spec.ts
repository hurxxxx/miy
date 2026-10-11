import { expect, test, type Page } from '@playwright/test';
import { createServer, type IncomingHttpHeaders } from 'node:http';
import type { AddressInfo } from 'node:net';
import {
  FAKE_COMPANY_USER,
  stubAppDataBackend,
  stubShellBackend,
} from './helpers';

// API/callback transport is synthetic. The real portal bundle runs in Chromium.
const core = 'https://registration-core.example.test';
const workbench = 'http://127.0.0.1:38102';
const actor = 'c0000000-0000-4000-8000-000000000001';
const requestId = 'a0000000-0000-4000-8000-000000000001';
const operationId = 'b0000000-0000-4000-8000-000000000001';
const code = `miyrc_${'s'.repeat(43)}`;
const api = '/api/v1/independent-apps/bootstrap-authorizations';
const callback = `${workbench}/api/registration-authorizations/callback`;
const query = new URLSearchParams({
  v: '1',
  request_id: requestId,
  operation_id: operationId,
  audience: workbench,
  code_challenge: 'c'.repeat(43),
  app_id: 'personal-notes',
  development_origin: 'https://notes.example.test',
  runtime_profile: 'web-api-postgres-v1',
  requested_permissions: 'data:read,identity:read',
});
const policy = {
  app_id: 'personal-notes',
  origin: 'https://notes.example.test',
  runtime_profile: 'web-api-postgres-v1',
  requested_permissions: ['data:read', 'identity:read'],
};
const response = () => ({
  schema_version: 1,
  id: 'd0000000-0000-4000-8000-000000000001',
  request_id: requestId,
  operation_id: operationId,
  actor_user_id: actor,
  audience: workbench,
  callback_url: callback,
  policy,
  code,
  code_expires_at: new Date(Date.now() + 120_000).toISOString(),
  expires_at: new Date(Date.now() + 300_000).toISOString(),
});

async function portal(page: Page, baseURL: string | undefined) {
  if (!baseURL) throw new Error('Browser test server URL is required');
  // Only static content is proxied to the local test server. Unknown API calls
  // fail inside the fixture; none can reach a real Core or Workbench service.
  await page.context().route(`${core}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/'))
      return route.fulfill({
        status: 404,
        json: { detail: 'Unconfigured synthetic endpoint' },
      });
    const result = await route.fetch({
      url: `${baseURL}${url.pathname}${url.search}`,
    });
    await route.fulfill({
      response: result,
      headers: {
        ...result.headers(),
        'referrer-policy': 'no-referrer',
      },
    });
  });
  await stubAppDataBackend(page);
  await stubShellBackend(page, { user: { ...FAKE_COMPANY_USER, id: actor } });
  // The shared fixture seeds only its local baseURL, while this test deliberately
  // serves the portal under a separate HTTPS origin.
  await page.addInitScript((origin) => {
    if (window.location.origin === origin)
      localStorage.setItem('miy.auth.token', 'e2e-test-token');
  }, core);
}

test('HTTPS portal consent returns by exact-Origin form POST to HTTP loopback without exposing the code in URLs', async ({
  page,
  baseURL,
}) => {
  await portal(page, baseURL);
  await page.context().addCookies([
    {
      name: 'synthetic_wb_session',
      value: 'fixture-only',
      domain: '127.0.0.1',
      path: '/',
      httpOnly: true,
      sameSite: 'Strict',
    },
  ]);
  let approvals = 0;
  const callbacks: {
    method: string;
    headers: IncomingHttpHeaders;
    body: string;
  }[] = [];
  let sameOriginSession = false;
  const urls: string[] = [];
  page.on('request', (request) => urls.push(request.url()));
  // Use an owned HTTP fixture so Chromium follows an actual 303 redirect.
  // Playwright interception alone does not intercept every hop in a redirect chain.
  const server = createServer((request, result) => {
    if (request.url === '/api/registration-authorizations/callback') {
      let body = '';
      request.on('data', (chunk: Buffer) => {
        body += chunk.toString();
      });
      request.on('end', () => {
        callbacks.push({
          method: request.method ?? '',
          headers: request.headers,
          body,
        });
        result.writeHead(303, { location: `/?registration=${requestId}` });
        result.end();
      });
      return;
    }
    if (request.url === '/api/synthetic-session') {
      sameOriginSession =
        request.headers.cookie === 'synthetic_wb_session=fixture-only';
      result.writeHead(200, { 'content-type': 'application/json' });
      result.end(JSON.stringify({ session: sameOriginSession }));
      return;
    }
    result.writeHead(200, { 'content-type': 'text/html' });
    result.end(
      '<p>Checking original Workbench session</p><script>fetch("/api/synthetic-session").then(r=>r.json()).then(r=>document.querySelector("p").textContent=r.session?"Original session retained":"Missing session")</script>',
    );
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const audience = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const consentQuery = new URLSearchParams(query);
  consentQuery.set('audience', audience);
  try {
    await page.route(`${core}${api}`, async (route) => {
      approvals++;
      const request = route.request();
      expect(request.method()).toBe('POST');
      expect(request.headers()['referer']).toBeUndefined();
      expect(request.postDataJSON()).toEqual({
        schema_version: 1,
        request_id: requestId,
        operation_id: operationId,
        audience,
        code_challenge: 'c'.repeat(43),
        policy,
      });
      await route.fulfill({
        json: {
          ...response(),
          audience,
          callback_url: `${audience}/api/registration-authorizations/callback`,
        },
      });
    });
    await page.goto(`${core}/apps/authorize-registration?${consentQuery}`);
    await expect(
      page.getByRole('heading', { name: 'Workbench 앱 등록 허용' }),
    ).toBeVisible();
    expect(approvals).toBe(0);
    await expect(
      page.getByText('개인 데이터 저장 기능이 있는 웹 앱', { exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: '최초 등록 한 번 허용' }).click();
    await page.waitForURL(`${audience}/?registration=${requestId}`);
    await expect(page.getByText('Original session retained')).toBeVisible();
    expect(callbacks).toHaveLength(1);
    expect(callbacks[0].method).toBe('POST');
    expect(callbacks[0].headers.origin).toBe(core);
    expect([undefined, `${core}/`]).toContain(callbacks[0].headers.referer);
    expect(callbacks[0].headers.cookie).toBeUndefined();
    expect(Object.fromEntries(new URLSearchParams(callbacks[0].body))).toEqual({
      request_id: requestId,
      code,
    });
    expect(sameOriginSession).toBe(true);
    expect(approvals).toBe(1);
    expect(
      urls.every(
        (url) =>
          !url.includes(code) &&
          !url.includes('code_verifier') &&
          !url.includes('miyrg_'),
      ),
    ).toBe(true);
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
      server.closeAllConnections();
    });
  }
});

test('portal rejects a substituted callback before creating a form', async ({
  page,
  baseURL,
}) => {
  await portal(page, baseURL);
  let approvals = 0;
  await page.route(`${core}${api}`, async (route) => {
    approvals++;
    await route.fulfill({
      json: {
        ...response(),
        callback_url: 'https://other.example.test/callback',
      },
    });
  });
  await page.goto(`${core}/apps/authorize-registration?${query}`);
  await page.getByRole('button', { name: '최초 등록 한 번 허용' }).click();
  await expect(page.getByRole('alert')).toContainText(
    '허용 결과를 확인하지 못했습니다',
  );
  await expect(
    page.getByRole('button', { name: '최초 등록 한 번 허용' }),
  ).toBeDisabled();
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(approvals).toBe(1);
});

test('unsupported Core keeps the existing registration file fallback available', async ({
  page,
  baseURL,
}) => {
  await portal(page, baseURL);
  await page.route(`${core}${api}`, (route) =>
    route.fulfill({
      status: 404,
      json: { detail: 'Unsupported synthetic endpoint' },
    }),
  );
  await page.goto(`${core}/apps/authorize-registration?${query}`);
  await page.getByRole('button', { name: '최초 등록 한 번 허용' }).click();
  await expect(page.getByRole('alert')).toContainText(
    '이 서버는 Workbench 등록 연결을 지원하지 않습니다',
  );
  await page.getByRole('link', { name: '등록 초안 파일로 진행' }).click();
  await expect(
    page.getByRole('heading', { name: '앱 등록', exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).pathname).toBe('/apps/register');
});

test('a repeated authorization query field never presents a consent action', async ({
  page,
  baseURL,
}) => {
  await portal(page, baseURL);
  await page.goto(
    `${core}/apps/authorize-registration?${query}&app_id=other-app`,
  );
  await expect(page.getByRole('alert')).toContainText(
    '유효한 등록 요청이 아닙니다',
  );
  await expect(
    page.getByRole('button', { name: '최초 등록 한 번 허용' }),
  ).toHaveCount(0);
});
