import { useEffect } from 'react';

const WIDGET_PATH = '/official-suite/widgets';

/** Pending writes keep the native document-close/reload confirmation active. */
export function usePendingDocumentLeaveProtection(pending: boolean): void {
  useEffect(() => {
    if (!pending) return;
    const owners = new Set<Window>([window]);
    try {
      if (
        window.frameElement?.getAttribute('src') === WIDGET_PATH &&
        window.parent.location.origin === window.location.origin
      )
        owners.add(window.parent);
    } catch {
      // Only the trusted same-origin owner receives the native protection.
    }
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    owners.forEach((owner) => owner.addEventListener('beforeunload', protect));
    return () =>
      owners.forEach((owner) =>
        owner.removeEventListener('beforeunload', protect),
      );
  }, [pending]);
}
