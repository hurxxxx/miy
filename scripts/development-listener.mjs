import { isIP } from 'node:net';

/**
 * @param {string | undefined} host
 * @param {string | number} port
 * @returns {URL}
 */
export function developmentListenerUrl(host, port) {
  const selectedHost = host ?? '127.0.0.1';
  const reachableHost =
    selectedHost === '0.0.0.0'
      ? '127.0.0.1'
      : selectedHost === '::'
        ? '::1'
        : selectedHost;
  if (
    typeof reachableHost !== 'string' ||
    (!isIP(reachableHost) &&
      !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/i.test(reachableHost))
  ) {
    throw new Error(
      'development listener host must be an IP address or hostname',
    );
  }
  const formattedHost =
    isIP(reachableHost) === 6 ? `[${reachableHost}]` : reachableHost;
  return new URL(`http://${formattedHost}:${port}/`);
}
