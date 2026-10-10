#!/usr/bin/env node

import { pathToFileURL } from 'node:url';

import { assertProductionAppEnv, readEnvFile } from './prod-app-config.mjs';
import { assertLoginPage } from './live-uat-preflight.mjs';

const REQUEST_TIMEOUT_MS = 15_000;

async function fetchResponse(label, url) {
  let response;
  try {
    response = await fetch(url, {
      redirect: 'follow',
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${label} request failed: ${detail}`);
  }
  return response;
}

async function fetchJson(label, url) {
  const response = await fetchResponse(label, url);
  if (!response.ok) {
    throw new Error(`${label} returned HTTP ${response.status}`);
  }
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new Error(`${label} did not return JSON`);
  }
  return response.json();
}

export async function assertDeploymentHealth(label, url, expectedRevision, composition) {
  const body = await fetchJson(label, url);
  assertDeploymentHealthBody(label, body, expectedRevision);
  if (composition && (body?.composition !== composition || body?.authority !== 'first_party_shared_database'))
    throw new Error(`${label} is not the expected first-party composition`);
}

function assertDeploymentHealthBody(label, body, expectedRevision) {
  if (body?.status !== 'ok') {
    throw new Error(`${label} reported status ${String(body?.status)}`);
  }
  if (body?.environment !== 'production') {
    throw new Error(`${label} is not running the production environment`);
  }
  if (expectedRevision && body?.runtime_revision !== expectedRevision) {
    throw new Error(`${label} is serving a different runtime revision`);
  }
}

export async function assertDeploymentReadiness(label, url, expectedRevision, composition) {
  const body = await fetchJson(label, url);
  if (body?.status !== 'ok') {
    throw new Error(`${label} reported status ${String(body?.status)}`);
  }
  if (body?.environment !== 'production') {
    throw new Error(`${label} is not running the production environment`);
  }
  if (body?.runtime_revision !== expectedRevision) {
    throw new Error(`${label} is serving a different runtime revision`);
  }
  if (composition && (body?.composition !== composition || body?.authority !== 'first_party_shared_database'))
    throw new Error(`${label} is not the expected first-party composition`);
}

export async function assertBootstrapJson(label, url) {
  const body = await fetchJson(label, url);
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new Error(`${label} returned an invalid JSON object`);
  }
}

export async function assertLegacyOfficialRouting({ appPort, publicBaseUrl }) {
  for (const [label, baseUrl] of [
    ['local legacy', new URL(`http://127.0.0.1:${appPort}/`)],
    ['public legacy', publicBaseUrl],
  ]) {
    // Earlier monolithic images serve this as their portal SPA. New legacy
    // images serve the extracted official shell; both must remain reachable.
    await assertLoginPage(`${label} official frontend`, new URL('/official-suite/widgets', baseUrl));
    const response = await fetchResponse(`${label} official routing`, new URL('/official-suite/healthz', baseUrl));
    const contentType = response.headers.get('content-type') ?? '';
    // A legacy assembly has no separate official health service. Older SPA
    // fallback HTML and the new reserved-path 404 are both expected; an official
    // JSON service or a dead split upstream is not a recovered legacy ingress.
    if (response.status !== 404 && (!response.ok || !contentType.toLowerCase().includes('text/html')))
      throw new Error(`${label} official routing still selects a separate or unavailable upstream`);
  }
}

export async function runProductionSmoke({
  appPort,
  publicBaseUrl,
  expectedRevision,
  topology = 'legacy',
  expectedOfficialRevision,
  apiPrefix = '/api/v1',
}) {
  if (!['legacy', 'first-party'].includes(topology) || (topology === 'first-party' && !expectedOfficialRevision))
    throw new Error('First-party smoke requires both immutable runtime revisions');
  const localBaseUrl = new URL(`http://127.0.0.1:${appPort}/`);
  for (const [label, baseUrl] of [
    ['local', localBaseUrl],
    ['public', publicBaseUrl],
  ]) {
    await assertDeploymentHealth(
      `${label} health`,
      new URL('/healthz', baseUrl),
      expectedRevision,
      topology === 'first-party' ? 'platform' : undefined,
    );
    await assertDeploymentReadiness(
      `${label} readiness`,
      new URL('/readyz', baseUrl),
      expectedRevision,
    );
    await assertBootstrapJson(
      `${label} bootstrap`,
      new URL(`${apiPrefix}/auth/bootstrap-status`, baseUrl),
    );
    await assertLoginPage(`${label} login`, new URL('/login', baseUrl));
  }
  if (topology === 'legacy') await assertLegacyOfficialRouting({ appPort, publicBaseUrl });
  if (topology === 'first-party') {
    let localCompatibility;
    for (const [label, baseUrl, healthPath, readyPath] of [
      ['local official', new URL('http://127.0.0.1:18780/'), '/healthz', '/readyz'],
      ['public official', publicBaseUrl, '/official-suite/healthz', '/official-suite/readyz'],
    ]) {
      await assertDeploymentHealth(`${label} health`, new URL(healthPath, baseUrl), expectedOfficialRevision, 'official');
      await assertDeploymentReadiness(`${label} readiness`, new URL(readyPath, baseUrl), expectedOfficialRevision, 'official');
      const compatibility = await fetchJson(`${label} frontend compatibility`, new URL('/official-suite/platform-build.json', baseUrl));
      if (!compatibility || typeof compatibility !== 'object' || Array.isArray(compatibility)
          || !Object.hasOwn(compatibility, 'platform_build_id') || (compatibility.platform_build_id !== null && typeof compatibility.platform_build_id !== 'string'))
        throw new Error(`${label} frontend compatibility is unavailable`);
      if (label === 'local official') localCompatibility = compatibility.platform_build_id;
      else if (compatibility.platform_build_id !== localCompatibility) throw new Error('Public official frontend differs from the local artifact');
      await assertLoginPage(`${label} frontend`, new URL('/official-suite/widgets', baseUrl));
    }
  }
}

async function runCli() {
  const envPath = process.argv[2] ?? '.env';
  const config = assertProductionAppEnv(readEnvFile(envPath));
  const expectedRevision = (
    process.env.MIY_EXPECTED_REVISION ?? ''
  ).trim();
  if (!expectedRevision) {
    throw new Error('MIY_EXPECTED_REVISION is required');
  }
  const args = process.argv.slice(3);
  if (args.length && (args.length !== 2 || args[0] !== '--topology' || args[1] !== 'first-party'))
    throw new Error('Invalid production smoke topology');
  const topology = args.length ? 'first-party' : 'legacy';
  const expectedOfficialRevision = (process.env.MIY_EXPECTED_OFFICIAL_REVISION ?? '').trim();
  await runProductionSmoke({ ...config, expectedRevision, topology, expectedOfficialRevision });
  process.stdout.write(
    'Production app smoke passed: local and public health, readiness, revision, bootstrap, and login shell are available.\n',
  );
}

const isMain =
  process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (isMain) {
  runCli().catch((error) => {
    const detail = error instanceof Error ? error.message : String(error);
    process.stderr.write(`Production app smoke failed: ${detail}\n`);
    process.exitCode = 1;
  });
}
