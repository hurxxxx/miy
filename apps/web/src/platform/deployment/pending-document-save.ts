import { useEffect } from 'react';

const WIDGET_PATH = '/official-suite/widgets';
const PENDING_SELECTOR = '[data-miy-pending-save="true"]';

/** Presentation readiness only; this never starts or acknowledges a save. */
export function hasPendingDocumentSaves(runtime: Window = window): boolean {
  if (runtime.document.querySelector(PENDING_SELECTOR)) return true;
  for (const frame of runtime.document.querySelectorAll('iframe')) {
    if (frame.getAttribute('src') !== WIDGET_PATH) continue;
    try {
      const child = frame.contentWindow;
      if (
        child?.location.origin === runtime.location.origin &&
        child.document.querySelector(PENDING_SELECTOR)
      )
        return true;
    } catch {
      // A foreign/navigated document cannot supply this first-party UI signal.
    }
  }
  return false;
}

export function waitForPendingDocumentSaves(
  signal: AbortSignal,
  runtime: Window = window,
): Promise<boolean> {
  return new Promise((resolve) => {
    let timer = 0;
    const finish = (ready: boolean) => {
      runtime.clearTimeout(timer);
      signal.removeEventListener('abort', cancel);
      resolve(ready);
    };
    const cancel = () => finish(false);
    const check = () => {
      if (signal.aborted) return finish(false);
      if (!hasPendingDocumentSaves(runtime)) return finish(true);
      timer = runtime.setTimeout(check, 100);
    };
    signal.addEventListener('abort', cancel, { once: true });
    check();
  });
}

/** Native reload/close also protects an embedded widget's owning document. */
export function usePendingDocumentSaveProtection(pending: boolean): void {
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
      // Only the trusted same-origin owner can receive this native protection.
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
