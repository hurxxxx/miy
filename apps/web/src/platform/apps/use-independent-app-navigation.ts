import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';

import {
  resolveIndependentNavigation,
  type IndependentNavigationDestination,
  type IndependentNavigationSource,
} from './independent-app-navigation';
import type {
  IndependentNavigationStatus,
  IndependentNavigationTarget,
} from './independent-app-host';

interface Offer {
  scope: object;
  destination: IndependentNavigationDestination;
  signal: AbortSignal;
  isCurrent: () => boolean;
  expiresAt: number;
  clear: () => void;
  checking: boolean;
  cancelRequest?: () => void;
}

/** One ephemeral suggestion tied to this exact login, source and document. */
export function useIndependentAppNavigation({
  token,
  actorId,
  source,
  documentVersion,
  locale,
  navigate,
}: {
  token: string | null;
  actorId: string | null;
  source: IndependentNavigationSource | null;
  documentVersion: string;
  locale: string;
  navigate: (path: string) => void;
}) {
  const scope = useMemo(
    () => ({}),
    [
      token,
      actorId,
      source?.appId,
      source?.installationId,
      source?.origin,
      source?.generation,
      source?.entrypoint,
      documentVersion,
    ],
  );
  const current = useRef(scope);
  current.current = scope;
  const active = useRef(true);
  const occupied = useRef<object | null>(null);
  const currentOffer = useRef<Offer | null>(null);
  const [offer, setOffer] = useState<Offer | null>(null);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      currentOffer.current?.clear();
      occupied.current = null;
    };
  }, [scope]);
  const live = useCallback(
    (signal: AbortSignal) =>
      active.current && current.current === scope && !signal.aborted,
    [scope],
  );
  const offerNavigation = useCallback(
    async (
      target: IndependentNavigationTarget,
      signal: AbortSignal,
      isCurrent: () => boolean,
    ): Promise<IndependentNavigationStatus> => {
      if (!token || !actorId || !source || !live(signal) || !isCurrent())
        return 'unavailable';
      if (occupied.current) return 'busy';
      const request = {};
      occupied.current = request;
      try {
        const destination = await resolveIndependentNavigation({
          token,
          actorId,
          source,
          target,
          locale,
          signal,
        });
        if (
          !live(signal) ||
          !isCurrent() ||
          occupied.current !== request ||
          !destination
        )
          return 'unavailable';
        const next: Offer = {
          scope,
          destination,
          signal,
          isCurrent,
          expiresAt: Date.now() + 30000,
          checking: false,
          clear: () => {
            next.cancelRequest?.();
            clearTimeout(timer);
            signal.removeEventListener('abort', next.clear);
            if (currentOffer.current !== next) return;
            currentOffer.current = null;
            occupied.current = null;
            setOffer(null);
          },
        };
        currentOffer.current = next;
        const timer = setTimeout(next.clear, 30000);
        signal.addEventListener('abort', next.clear, { once: true });
        setOffer(next);
        return 'offered';
      } catch {
        return 'unavailable';
      } finally {
        if (occupied.current === request && !currentOffer.current)
          occupied.current = null;
      }
    },
    [token, actorId, source, locale, scope, live],
  );
  const accept = useCallback(async () => {
    const selected = currentOffer.current;
    if (
      !selected ||
      selected.checking ||
      selected.scope !== scope ||
      !token ||
      !actorId ||
      !source
    )
      return;
    selected.checking = true;
    setOffer({ ...selected });
    const controller = new AbortController();
    selected.cancelRequest = () => controller.abort();
    const cancel = () => {
      controller.abort();
      selected.clear();
    };
    selected.signal.addEventListener('abort', cancel, { once: true });
    const timeout = setTimeout(cancel, 8000);
    try {
      if (
        !live(selected.signal) ||
        !selected.isCurrent() ||
        Date.now() >= selected.expiresAt
      )
        return;
      const fresh = await resolveIndependentNavigation({
        token,
        actorId,
        source,
        target: selected.destination.target,
        locale,
        signal: controller.signal,
      });
      if (
        !live(selected.signal) ||
        !selected.isCurrent() ||
        controller.signal.aborted ||
        currentOffer.current !== selected ||
        Date.now() >= selected.expiresAt ||
        !fresh ||
        fresh.identity !== selected.destination.identity ||
        fresh.path !== selected.destination.path
      )
        return;
      selected.clear();
      navigate(fresh.path);
    } catch {
      /* Failed admission leaves the user on this page. */
    } finally {
      clearTimeout(timeout);
      selected.signal.removeEventListener('abort', cancel);
      selected.clear();
    }
  }, [scope, token, actorId, source, locale, live, navigate]);
  return {
    offer: offer?.scope === scope ? offer : null,
    offerNavigation,
    accept,
    dismiss: () => currentOffer.current?.clear(),
  };
}
