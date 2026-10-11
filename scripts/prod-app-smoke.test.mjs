import assert from 'node:assert/strict';
import test from 'node:test';

import {
  assertBootstrapJson,
  assertDeploymentHealth,
  assertDeploymentReadiness,
  assertLegacyOfficialRouting,
  runProductionSmoke,
} from './prod-app-smoke.mjs';

for (const publicHealth of ['html', 'not-found', 'official', 'unavailable']) {
  test(`legacy routing ${['html', 'not-found'].includes(publicHealth) ? 'accepts' : 'rejects'} ${publicHealth} official namespace`, async (context) => {
    const originalFetch = globalThis.fetch;
    context.after(() => { globalThis.fetch = originalFetch; });
    globalThis.fetch = async (url) => {
      const target = new URL(url);
      if (target.protocol === 'https:' && target.pathname.endsWith('/healthz')) {
        if (publicHealth === 'not-found') return new Response('', { status: 404 });
        if (publicHealth === 'official') return new Response(JSON.stringify({ composition: 'official' }), { headers: { 'content-type': 'application/json' } });
        if (publicHealth === 'unavailable') return new Response('', { status: 502 });
      }
      return new Response('<!doctype html><html><body><div id="root"></div></body></html>', { headers: { 'content-type': 'text/html' } });
    };
    const check = () => assertLegacyOfficialRouting({ appPort: 8000, publicBaseUrl: new URL('https://portal.example.com') });
    if (['html', 'not-found'].includes(publicHealth)) await check();
    else await assert.rejects(check(), /separate or unavailable upstream/);
  });
}

for (const wrongPublicComposition of [false, true]) {
  test(`first-party smoke ${wrongPublicComposition ? 'rejects an ingress still serving platform' : 'checks the independent official source and web'}`, async (context) => {
    const originalFetch = globalThis.fetch;
    context.after(() => { globalThis.fetch = originalFetch; });
    const requests = [];
    globalThis.fetch = async (url) => {
      const target = new URL(url);
      requests.push(`${target.origin}${target.pathname}`);
      if (target.pathname === '/login' || target.pathname === '/official-suite/widgets')
        return new Response('<!doctype html><html><body><div id="root"></div></body></html>', { headers: { 'content-type': 'text/html' } });
      if (target.pathname === '/official-suite/platform-build.json')
        return new Response(JSON.stringify({ platform_build_id: null }), { headers: { 'content-type': 'application/json' } });
      const official = target.port === '18780' || target.pathname.startsWith('/official-suite/');
      const misrouted = wrongPublicComposition && target.protocol === 'https:' && official;
      return new Response(JSON.stringify({
        status: 'ok', environment: 'production', runtime_revision: official ? 'official-revision' : 'platform-revision',
        composition: official && !misrouted ? 'official' : 'platform', authority: 'first_party_shared_database',
      }), { headers: { 'content-type': 'application/json' } });
    };
    const smoke = () => runProductionSmoke({ appPort: 8000, publicBaseUrl: new URL('https://portal.example.com'),
      expectedRevision: 'platform-revision', expectedOfficialRevision: 'official-revision', topology: 'first-party' });
    if (wrongPublicComposition) await assert.rejects(smoke(), /expected first-party composition/);
    else {
      await smoke();
      assert.ok(requests.includes('http://127.0.0.1:18780/readyz'));
      assert.ok(requests.includes('https://portal.example.com/official-suite/readyz'));
      assert.ok(requests.includes('https://portal.example.com/official-suite/widgets'));
    }
  });
}

test('validates production health and the expected revision', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        status: 'ok',
        environment: 'production',
        runtime_revision: 'abc123',
      }),
      { headers: { 'content-type': 'application/json' } },
    );

  await assertDeploymentHealth(
    'health',
    new URL('https://prod.example.com/healthz'),
    'abc123',
  );
  await assert.rejects(
    assertDeploymentHealth(
      'health',
      new URL('https://prod.example.com/healthz'),
      'other',
    ),
    /different runtime revision/,
  );
});

test('requires production readiness at the expected revision', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        status: 'ok',
        environment: 'production',
        runtime_revision: 'abc123',
      }),
      { headers: { 'content-type': 'application/json' } },
    );

  await assertDeploymentReadiness(
    'readiness',
    new URL('https://prod.example.com/readyz'),
    'abc123',
  );
});

test('requires bootstrap JSON objects', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ initialized: true }), {
      headers: { 'content-type': 'application/json' },
    });
  await assertBootstrapJson(
    'bootstrap',
    new URL('https://prod.example.com/api/v1/auth/bootstrap-status'),
  );
});

test('checks local and public surfaces in one smoke loop', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => {
    globalThis.fetch = originalFetch;
  });
  const requestedPaths = [];
  globalThis.fetch = async (url) => {
    const parsed = new URL(url);
    requestedPaths.push(`${parsed.origin}${parsed.pathname}`);
    if (parsed.pathname === '/login' || parsed.pathname.startsWith('/official-suite/')) {
      return new Response(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        { headers: { 'content-type': 'text/html' } },
      );
    }
    if (parsed.pathname === '/healthz' || parsed.pathname === '/readyz') {
      return new Response(
        JSON.stringify({
          status: 'ok',
          environment: 'production',
          runtime_revision: 'abc123',
        }),
        { headers: { 'content-type': 'application/json' } },
      );
    }
    return new Response(JSON.stringify({ initialized: true }), {
      headers: { 'content-type': 'application/json' },
    });
  };

  await runProductionSmoke({
    appPort: 8000,
    publicBaseUrl: new URL('https://prod.example.com/'),
    expectedRevision: 'abc123',
  });
  assert.deepEqual(requestedPaths, [
    'http://127.0.0.1:8000/healthz',
    'http://127.0.0.1:8000/readyz',
    'http://127.0.0.1:8000/api/v1/auth/bootstrap-status',
    'http://127.0.0.1:8000/login',
    'https://prod.example.com/healthz',
    'https://prod.example.com/readyz',
    'https://prod.example.com/api/v1/auth/bootstrap-status',
    'https://prod.example.com/login',
    'http://127.0.0.1:8000/official-suite/widgets',
    'http://127.0.0.1:8000/official-suite/healthz',
    'https://prod.example.com/official-suite/widgets',
    'https://prod.example.com/official-suite/healthz',
  ]);
});
