import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  assertJsonEndpoint,
  assertJsonObjectEndpoint,
  assertLoginPage,
  assertMatchingDevRuntime,
  assertOkEndpoint,
  assertRuntimeStatus,
  assertWorkerPing,
  developmentListenerUrl,
  normalizePublicBaseUrl,
  runPublicDevSmoke,
} from './live-uat-preflight.mjs';

test('development smoke connects to the configured listener', () => {
  for (const [host, expected] of [
    [undefined, 'http://127.0.0.1:8001/'],
    ['172.17.0.1', 'http://172.17.0.1:8001/'],
    ['0.0.0.0', 'http://127.0.0.1:8001/'],
    ['::', 'http://[::1]:8001/'],
    ['::1', 'http://[::1]:8001/'],
    ['dev.example.com', 'http://dev.example.com:8001/'],
  ]) {
    assert.equal(developmentListenerUrl(host, '8001').href, expected);
  }
  for (const host of [
    '',
    'http://host',
    'user@host',
    'host/path',
    'host?key=x',
  ]) {
    assert.throws(() => developmentListenerUrl(host, '8001'));
  }
});

test('login smoke reaches a nondefault listener without reading checkout credentials', async (context) => {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push(request.url);
    const bodies = {
      '/healthz': { status: 'ok' },
      '/api/v1/auth/login': { token: 'synthetic-token' },
      '/api/v1/auth/me': {
        login_id: 'administrator',
        email: 'synthetic@example.com',
        system_roles: ['platform_admin'],
      },
      '/api/v1/apps/bootstrap': { apps: [{ app_id: 'synthetic' }] },
    };
    response.writeHead(bodies[request.url] ? 200 : 404, {
      'content-type': 'application/json',
    });
    response.end(JSON.stringify(bodies[request.url] ?? {}));
  });
  server.listen(0, '127.0.0.2');
  await once(server, 'listening');
  context.after(() => new Promise((resolve) => server.close(resolve)));
  const child = spawn(
    'bash',
    [fileURLToPath(new URL('./dev-login-smoke.sh', import.meta.url))],
    {
      env: {
        PATH: process.env.PATH,
        MIY_SKIP_DOTENV: '1',
        MIY_DEV_API_HOST: '127.0.0.2',
        MIY_API_DEV_PORT: String(server.address().port),
        MIY_DEV_SMOKE_API_URL: '',
        MIY_API_DEV_LOGIN_PASSWORD: 'synthetic-password',
      },
      stdio: ['ignore', 'ignore', 'ignore'],
    },
  );
  context.after(() => {
    if (child.exitCode === null) child.kill('SIGTERM');
  });
  const timer = setTimeout(() => child.kill('SIGTERM'), 8000);
  const [exitCode] = await once(child, 'close');
  clearTimeout(timer);
  assert.equal(exitCode, 0);
  assert.deepEqual(requests, [
    '/healthz',
    '/api/v1/auth/login',
    '/api/v1/auth/me',
    '/api/v1/apps/bootstrap',
  ]);
});

test('browser login smoke loads the checkout env contract', async () => {
  const packageJson = JSON.parse(
    await readFile(new URL('../package.json', import.meta.url), 'utf8'),
  );
  assert.equal(
    packageJson.scripts['dev:login-browser-smoke'],
    "bash -c 'source ./scripts/dev-env.sh && node ./scripts/dev-login-browser-smoke.mjs'",
  );
});

test('accepts only credential-free HTTPS public origins', () => {
  assert.equal(
    normalizePublicBaseUrl('https://miy.example.com').href,
    'https://miy.example.com/',
  );
  for (const value of [
    '',
    'http://miy.example.com',
    'https://localhost:4200',
    'https://127.0.0.1',
    'https://miy',
    'https://user:password@miy.example.com',
    'https://miy.example.com/app',
    'https://miy.example.com/?token=secret',
  ]) {
    assert.throws(() => normalizePublicBaseUrl(value));
  }
});

test('requires all three development services', () => {
  const ready = 'web    running\napi    running\nworker running\n';
  assert.doesNotThrow(() => assertRuntimeStatus(ready));
  assert.throws(
    () => assertRuntimeStatus('web running\napi running\n'),
    /worker/,
  );
  assert.doesNotThrow(() => assertWorkerPing('worker@example: OK\n  pong'));
  assert.throws(() =>
    assertWorkerPing('No nodes replied within time constraint'),
  );
  assert.doesNotThrow(() =>
    assertRuntimeStatus('web running\napi running\n', ['web', 'api']),
  );
});

test('requires public health to identify the local development runtime', () => {
  const health = {
    status: 'ok',
    version: '0.1.1',
    environment: 'development',
    instance_id: 'dev-api',
    runtime_revision: 'abc123',
  };
  assert.doesNotThrow(() => assertMatchingDevRuntime(health, { ...health }));
  assert.throws(
    () =>
      assertMatchingDevRuntime(health, {
        ...health,
        runtime_revision: 'stale-revision',
      }),
    /runtime_revision/,
  );
  assert.throws(
    () =>
      assertMatchingDevRuntime(
        { ...health, environment: 'production' },
        { ...health, environment: 'production' },
      ),
    /development runtime/,
  );
});

test('validates health JSON and the login HTML shell', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });

  globalThis.fetch = async () =>
    new Response(JSON.stringify({ status: 'ok' }), {
      headers: { 'content-type': 'application/json' },
    });
  await assertJsonEndpoint(
    'ready',
    new URL('https://miy.example.com/readyz'),
    'ok',
  );
  await assertOkEndpoint(
    'storage',
    new URL('https://storage.example.com/health'),
  );
  await assertJsonObjectEndpoint(
    'bootstrap',
    new URL('https://miy.example.com/api/v1/auth/bootstrap-status'),
  );

  globalThis.fetch = async () =>
    new Response(
      '<!doctype html><html><body><div id="root"></div></body></html>',
      {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      },
    );
  await assertLoginPage('login', new URL('https://miy.example.com/login'));

  globalThis.fetch = async () =>
    new Response('<html><body>Service unavailable</body></html>', {
      headers: { 'content-type': 'text/html' },
    });
  await assert.rejects(
    assertLoginPage('login', new URL('https://miy.example.com/login')),
    /rendered web shell/,
  );
});

test('public dev smoke covers the local runtime and public ingress', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  const requested = [];
  globalThis.fetch = async (url) => {
    const parsed = new URL(url);
    requested.push(`${parsed.origin}${parsed.pathname}`);
    if (parsed.pathname === '/' || parsed.pathname === '/login') {
      return new Response(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        { headers: { 'content-type': 'text/html' } },
      );
    }
    if (parsed.pathname === '/api/v1/auth/bootstrap-status') {
      return new Response(JSON.stringify({ initialized: true }), {
        headers: { 'content-type': 'application/json' },
      });
    }
    return new Response(
      JSON.stringify({
        status: 'ok',
        version: '0.1.1',
        environment: 'development',
        instance_id: 'dev-api',
        runtime_revision: 'abc123',
      }),
      { headers: { 'content-type': 'application/json' } },
    );
  };

  await runPublicDevSmoke({
    env: {
      MIY_API_DEV_PORT: '8002',
      MIY_UAT_BASE_URL: 'https://miy.example.com',
      MIY_WEB_DEV_PORT: '4200',
    },
    statusOutput: 'web running\napi running\n',
    report: false,
  });

  assert.deepEqual(requested, [
    'http://127.0.0.1:8002/healthz',
    'https://miy.example.com/healthz',
    'http://127.0.0.1:8002/readyz',
    'https://miy.example.com/readyz',
    'http://127.0.0.1:8002/api/v1/auth/bootstrap-status',
    'https://miy.example.com/api/v1/auth/bootstrap-status',
    'http://127.0.0.1:4200/',
    'http://127.0.0.1:4200/login',
    'https://miy.example.com/',
    'https://miy.example.com/login',
  ]);
});

test('public dev smoke fails closed on a public bad gateway', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async (url) => {
    const parsed = new URL(url);
    if (parsed.origin === 'https://miy.example.com') {
      return new Response('Bad Gateway', {
        status: 502,
        headers: { 'content-type': 'text/plain' },
      });
    }
    return new Response(
      JSON.stringify({
        status: 'ok',
        version: '0.1.1',
        environment: 'development',
        instance_id: 'dev-api',
        runtime_revision: 'abc123',
      }),
      { headers: { 'content-type': 'application/json' } },
    );
  };

  await assert.rejects(
    runPublicDevSmoke({
      env: {
        MIY_API_DEV_PORT: '8002',
        MIY_UAT_BASE_URL: 'https://miy.example.com',
        MIY_WEB_DEV_PORT: '4200',
      },
      statusOutput: 'web running\napi running\n',
      report: false,
    }),
    /public health returned HTTP 502/,
  );
});

test('public dev smoke uses distinct configured API and web listeners', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  const requested = [];
  globalThis.fetch = async (url) => {
    const parsed = new URL(url);
    requested.push(parsed.origin);
    if (parsed.pathname === '/' || parsed.pathname === '/login') {
      return new Response('<html><div id="root"></div></html>', {
        headers: { 'content-type': 'text/html' },
      });
    }
    return new Response(
      JSON.stringify({
        status: 'ok',
        version: '0.1.1',
        environment: 'development',
        instance_id: 'dev-api',
        runtime_revision: 'abc123',
      }),
      { headers: { 'content-type': 'application/json' } },
    );
  };
  await runPublicDevSmoke({
    env: {
      MIY_DEV_API_HOST: '192.0.2.10',
      MIY_API_DEV_PORT: '8002',
      MIY_WEB_DEV_HOST: '192.0.2.11',
      MIY_WEB_DEV_PORT: '4201',
      MIY_UAT_BASE_URL: 'https://miy.example.com',
    },
    statusOutput: 'web running\napi running\n',
    report: false,
  });
  assert.deepEqual(
    [...new Set(requested)],
    [
      'http://192.0.2.10:8002',
      'https://miy.example.com',
      'http://192.0.2.11:4201',
    ],
  );
});
