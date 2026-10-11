export { usePendingDocumentLeaveProtection as usePendingDocumentSaveProtection } from '@miy/platform-web/document-leave-protection';

const WIDGET_PATH = '/official-suite/widgets';
const PENDING_SELECTOR = '[data-miy-pending-save="true"]';

/** Pending document writes, including an entire queued upload batch.
 * Presentation readiness only; this never starts or acknowledges a write.
 */
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
