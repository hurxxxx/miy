import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FLOATING_DM_OPEN_EVENT,
  FLOATING_PMS_OPEN_EVENT,
} from '@miy/platform-web/personal-widgets/floating-panel-events';

const WIDGET_PATH = '/official-suite/widgets';

/** Clip the trusted document to its visible dock/panels so the portal remains clickable. */
export function widgetSurfaceClip(
  rects: readonly Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>[],
  width: number,
  height: number,
): string {
  const paths = rects
    .map((rect) => {
      const left = Math.max(0, Math.min(width, rect.left));
      const right = Math.max(left, Math.min(width, rect.right));
      const top = Math.max(0, Math.min(height, rect.top));
      const bottom = Math.max(top, Math.min(height, rect.bottom));
      return right > left && bottom > top
        ? `M${left},${top}H${right}V${bottom}H${left}Z`
        : '';
    })
    .filter(Boolean);
  return `path('${paths.join(' ') || 'M0,0H0V0Z'}')`;
}

/** Only a fixed first-party document is embedded; no token or app authority is sent. */
export function OfficialWidgetFrame() {
  const { t } = useTranslation('shell');
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [generation, setGeneration] = useState(0);
  const [clipPath, setClipPath] = useState("path('M0,0H0V0Z')");

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let doc: Document | null;
    try {
      // Cross-origin/navigation changes cannot be granted a visible overlay.
      if (
        frame.contentWindow?.location.origin !== window.location.origin ||
        frame.contentWindow.location.pathname !== WIDGET_PATH
      )
        return;
      doc = frame.contentDocument;
    } catch {
      return;
    }
    if (!doc?.body) return;
    const widgetDocument = doc;
    let pending = 0;
    const observed = new Set<Element>();
    const update = () => {
      pending = 0;
      const surfaces = [
        ...widgetDocument.querySelectorAll(
          '[data-miy-embedded-surface], [role="dialog"], [role="alert"], [data-ui-overlay]',
        ),
      ];
      for (const element of surfaces) {
        if (!observed.has(element)) {
          observed.add(element);
          resize.observe(element);
        }
      }
      const rects = surfaces
        .filter((element) => !element.closest('[hidden], [aria-hidden="true"]'))
        .map((element) => element.getBoundingClientRect());
      setClipPath(
        widgetSurfaceClip(rects, window.innerWidth, window.innerHeight),
      );
    };
    const schedule = () => {
      if (!pending) pending = window.requestAnimationFrame(update);
    };
    const resize = new ResizeObserver(schedule);
    const mutations = new MutationObserver(schedule);
    mutations.observe(widgetDocument.body, {
      attributes: true,
      childList: true,
      subtree: true,
    });
    const forwardPanelEvent = (event: Event) => {
      // Existing UI-only event contract; the child still authenticates every API request.
      frame.contentWindow?.dispatchEvent(
        new CustomEvent(event.type, {
          detail: event instanceof CustomEvent ? event.detail : undefined,
        }),
      );
    };
    window.addEventListener(FLOATING_DM_OPEN_EVENT, forwardPanelEvent);
    window.addEventListener(FLOATING_PMS_OPEN_EVENT, forwardPanelEvent);
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      window.cancelAnimationFrame(pending);
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener('resize', schedule);
      window.removeEventListener(FLOATING_DM_OPEN_EVENT, forwardPanelEvent);
      window.removeEventListener(FLOATING_PMS_OPEN_EVENT, forwardPanelEvent);
    };
  }, [generation]);

  return (
    <div className="h-full w-10 shrink-0 border-l border-app-border bg-app-bg">
      <iframe
        ref={frameRef}
        src={WIDGET_PATH}
        title={t('personalWidgets.dockLabel')}
        onLoad={() => {
          setClipPath("path('M0,0H0V0Z')");
          setGeneration((value) => value + 1);
        }}
        className="fixed inset-0 z-[var(--ui-z-floating-panel)] h-dvh w-screen border-0 bg-transparent"
        style={{ clipPath }}
      />
    </div>
  );
}
