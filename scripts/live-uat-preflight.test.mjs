import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import {
  assertJsonEndpoint,
  assertJsonObjectEndpoint,
  assertLoginPage,
  assertMatchingDevRuntime,
  assertOkEndpoint,
  assertRuntimeStatus,
  assertWorkerPing,
  normalizePublicBaseUrl,
  runPublicDevSmoke,
} from './live-uat-preflight.mjs';

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
    normalizePublicBaseUrl('https://mty.example.com').href,
    'https://mty.example.com/',
  );
  for (const value of [
    '',
    'http://mty.example.com',
    'https://localhost:4200',
    'https://127.0.0.1',
    'https://mty',
    'https://user:password@mty.example.com',
    'https://mty.example.com/app',
    'https://mty.example.com/?token=secret',
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
    new URL('https://mty.example.com/readyz'),
    'ok',
  );
  await assertOkEndpoint(
    'storage',
    new URL('https://storage.example.com/health'),
  );
  await assertJsonObjectEndpoint(
    'bootstrap',
    new URL('https://mty.example.com/api/v1/auth/bootstrap-status'),
  );

  globalThis.fetch = async () =>
    new Response(
      '<!doctype html><html><body><div id="root"></div></body></html>',
      {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      },
    );
  await assertLoginPage('login', new URL('https://mty.example.com/login'));

  globalThis.fetch = async () =>
    new Response('<html><body>Service unavailable</body></html>', {
      headers: { 'content-type': 'text/html' },
    });
  await assert.rejects(
    assertLoginPage('login', new URL('https://mty.example.com/login')),
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
      MTY_API_DEV_PORT: '8002',
      MTY_UAT_BASE_URL: 'https://mty.example.com',
      MTY_WEB_DEV_PORT: '4200',
    },
    statusOutput: 'web running\napi running\n',
    report: false,
  });

  assert.deepEqual(requested, [
    'http://127.0.0.1:8002/healthz',
    'https://mty.example.com/healthz',
    'http://127.0.0.1:8002/readyz',
    'https://mty.example.com/readyz',
    'http://127.0.0.1:8002/api/v1/auth/bootstrap-status',
    'https://mty.example.com/api/v1/auth/bootstrap-status',
    'http://127.0.0.1:4200/',
    'http://127.0.0.1:4200/login',
    'https://mty.example.com/',
    'https://mty.example.com/login',
  ]);
});

test('public dev smoke fails closed on a public bad gateway', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async (url) => {
    const parsed = new URL(url);
    if (parsed.origin === 'https://mty.example.com') {
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
        MTY_API_DEV_PORT: '8002',
        MTY_UAT_BASE_URL: 'https://mty.example.com',
        MTY_WEB_DEV_PORT: '4200',
      },
      statusOutput: 'web running\napi running\n',
      report: false,
    }),
    /public health returned HTTP 502/,
  );
});
