import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { ProxyOptions } from 'vite';
import contracts from '../../contracts/app-contracts.json';
import { developmentListenerUrl } from '../../../scripts/development-listener.mjs';

const ids = new Set<string>(contracts.official_app_ids);
const bases = contracts.apps
  .filter((app) => ids.has(app.app_id))
  .map((app) => app.route_base);
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
export const officialClientProxyPattern = `^(?:${bases.map(escape).join('|')})(?:/|\\?|$)`;
export const officialUiProxyKeys = [
  officialClientProxyPattern,
  '/official-suite',
  '/recording-sync-sw.js',
  '/help/pms/user-guide.html',
];

export function officialUiDevelopmentProxies(): Record<string, ProxyOptions> {
  return Object.fromEntries(
    officialUiProxyKeys.map((key) => [
      key,
      {
        target: 'http://127.0.0.1:4201',
        timeout: 0,
        proxyTimeout: 0,
        ws: true,
        rewrite:
          key === '/official-suite'
            ? undefined
            : (requestPath: string) => `/official-suite${requestPath}`,
      },
    ]),
  );
}

/** The launcher generates this route projection once from the actual server inventory. */
export function firstPartyApiDevelopmentProxies(
  mode: string,
): Record<string, ProxyOptions> {
  if (mode !== 'first-party') return {};
  const target = developmentListenerUrl(
    process.env.MIY_DEV_API_HOST,
    18781,
  ).origin;
  const file = fileURLToPath(
    new URL('../../../.runtime/first-party-api-routes.json', import.meta.url),
  );
  const value: unknown = JSON.parse(readFileSync(file, 'utf8'));
  if (
    !value ||
    typeof value !== 'object' ||
    !('api_prefix' in value) ||
    !('official_patterns' in value) ||
    typeof value.api_prefix !== 'string' ||
    !Array.isArray(value.official_patterns) ||
    value.official_patterns.length === 0
  ) {
    throw new Error('first_party_api_owner_inventory_invalid');
  }
  const patterns = value.official_patterns;
  if (
    !patterns.every(
      (pattern) =>
        typeof pattern === 'string' &&
        pattern.startsWith(`^${value.api_prefix}`) &&
        pattern.endsWith('$'),
    )
  ) {
    throw new Error('first_party_api_owner_inventory_invalid');
  }
  return Object.fromEntries(
    patterns.map((pattern: string) => [
      `${pattern.slice(0, -1)}(?:\\?.*)?$`,
      {
        target,
        timeout: 0,
        proxyTimeout: 0,
        ws: true,
      },
    ]),
  );
}
