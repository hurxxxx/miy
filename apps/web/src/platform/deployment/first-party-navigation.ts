import { APP_CONTRACTS, OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';

export type FirstPartyUiOwner = 'platform' | 'official';
const ids = new Set<string>(OFFICIAL_APP_IDS);
const officialBases = APP_CONTRACTS.filter((app) => ids.has(app.app_id)).map(
  (app) => app.route_base,
);

export function firstPartyUiOwner(path: string): FirstPartyUiOwner {
  return path === '/official-suite' ||
    path.startsWith('/official-suite/') ||
    officialBases.some((base) => path === base || path.startsWith(`${base}/`))
    ? 'official'
    : 'platform';
}

/** Reload the router's current entry without replacing its usr/state payload. */
export function reloadFirstPartyDocument(): void {
  window.location.reload();
}

/** App boundaries are document navigations, preserving query/hash and browser history. */
export function installFirstPartyNavigation(
  owner: FirstPartyUiOwner,
): () => void {
  const handler = (event: MouseEvent) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.altKey ||
      event.shiftKey
    )
      return;
    const anchor =
      event.target instanceof Element ? event.target.closest('a[href]') : null;
    if (
      !(anchor instanceof HTMLAnchorElement) ||
      anchor.download ||
      (anchor.target && anchor.target !== '_self')
    )
      return;
    const url = new URL(anchor.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    const embedded = owner === 'official' && window.parent !== window;
    if (
      embedded &&
      url.pathname === window.location.pathname &&
      url.search === window.location.search &&
      url.hash
    )
      return;
    if (!embedded && firstPartyUiOwner(url.pathname) === owner) return;
    event.preventDefault();
    (embedded ? window.parent : window).location.assign(
      `${url.pathname}${url.search}${url.hash}`,
    );
  };
  document.addEventListener('click', handler, true);
  return () => document.removeEventListener('click', handler, true);
}
