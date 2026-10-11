import { useEffect, useRef, type ReactNode } from 'react';
import { Route, Routes, useLocation } from 'react-router-dom';
import {
  hasPendingDocumentSaves,
  waitForPendingDocumentSaves,
} from './pending-document-save';
import {
  firstPartyUiOwner,
  reloadFirstPartyDocument,
  type FirstPartyUiOwner,
} from './first-party-navigation';

/** Router push/replace/back already owns the URL and native history state. */
export function FirstPartyDocumentBoundary({
  owner,
  children,
}: {
  owner: FirstPartyUiOwner | 'widget';
  children: ReactNode;
}) {
  const location = useLocation();
  const lastOwnedLocation = useRef(location);
  const crossesOwner =
    owner === 'widget'
      ? location.pathname !== '/official-suite/widgets'
      : firstPartyUiOwner(location.pathname) !== owner;
  if (!crossesOwner) {
    lastOwnedLocation.current = location;
  }
  useEffect(() => {
    if (!crossesOwner) return;
    const runtime = owner === 'widget' ? window.parent : window;
    const navigate = () => {
      if (runtime !== window) {
        // Both documents are trusted same-origin first-party UI. Preserve the
        // router's native usr state without a storage or token handoff.
        runtime.history.pushState(
          {
            ...window.history.state,
            idx: (runtime.history.state?.idx ?? 0) + 1,
          },
          '',
          `${location.pathname}${location.search}${location.hash}`,
        );
      }
      reloadFirstPartyDocument(runtime);
    };
    if (!hasPendingDocumentSaves(runtime)) return navigate();
    const transition = new AbortController();
    void waitForPendingDocumentSaves(transition.signal, runtime).then(
      (ready) => {
        if (ready) navigate();
      },
    );
    return () => transition.abort();
  }, [
    crossesOwner,
    location.key,
    location.pathname,
    location.search,
    location.hash,
    owner,
  ]);
  // Public location override preserves the previous UI and autosave owner while
  // native history keeps the new entry's usr/state for the eventual document.
  // Keep existing beforeunload handlers mounted even when no save is pending.
  return (
    <Routes location={crossesOwner ? lastOwnedLocation.current : location}>
      <Route path="*" element={children} />
    </Routes>
  );
}
