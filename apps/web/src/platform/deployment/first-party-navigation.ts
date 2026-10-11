import { APP_CONTRACTS, OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';
import {
  hasPendingDocumentSaves,
  waitForPendingDocumentSaves,
} from './pending-document-save';

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
export function reloadFirstPartyDocument(runtime: Window = window): void {
  runtime.location.reload();
}

/** App boundaries are document navigations, preserving query/hash and browser history. */
export function installFirstPartyNavigation(
  owner: FirstPartyUiOwner,
): () => void {
  let transition: AbortController | null = null;
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
    transition?.abort();
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
    const runtime = embedded ? window.parent : window;
    const navigate = () =>
      runtime.location.assign(`${url.pathname}${url.search}${url.hash}`);
    if (!hasPendingDocumentSaves(runtime)) return navigate();
    transition = new AbortController();
    void waitForPendingDocumentSaves(transition.signal, runtime).then(
      (ready) => {
        if (ready) navigate();
      },
    );
  };
  document.addEventListener('click', handler, true);
  return () => {
    transition?.abort();
    document.removeEventListener('click', handler, true);
  };
}
