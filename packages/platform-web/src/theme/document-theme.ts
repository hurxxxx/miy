import { useCallback, useEffect, useSyncExternalStore } from 'react';
import type { ThemePreference } from '../auth-types.js';

export type ResolvedThemePreference = 'light' | 'dark';
export const DARK_MODE_QUERY = '(prefers-color-scheme: dark)';

export function resolveThemePreference(
  themePreference: ThemePreference,
  systemDarkMode: boolean,
): ResolvedThemePreference {
  return themePreference === 'system'
    ? systemDarkMode
      ? 'dark'
      : 'light'
    : themePreference;
}

export function getSystemDarkModeSnapshot(): boolean {
  return typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function'
    ? window.matchMedia(DARK_MODE_QUERY).matches
    : false;
}

export function subscribeSystemDarkMode(onStoreChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function')
    return () => undefined;
  const mediaQuery = window.matchMedia(DARK_MODE_QUERY);
  mediaQuery.addEventListener('change', onStoreChange);
  return () => mediaQuery.removeEventListener('change', onStoreChange);
}

/** The same user/system theme owner for normal shells and trusted widget documents. */
export function useDocumentTheme(
  preference: ThemePreference = 'system',
  inheritedDocument?: Document,
): ResolvedThemePreference {
  const systemDarkMode = useSyncExternalStore(
    subscribeSystemDarkMode,
    getSystemDarkModeSnapshot,
    () => false,
  );
  const subscribeInheritedTheme = useCallback(
    (notify: () => void) => {
      if (!inheritedDocument) return () => undefined;
      const observer = new MutationObserver(notify);
      observer.observe(inheritedDocument.documentElement, {
        attributes: true,
        attributeFilter: ['class'],
      });
      return () => observer.disconnect();
    },
    [inheritedDocument],
  );
  const inheritedDarkMode = useSyncExternalStore(
    subscribeInheritedTheme,
    useCallback(
      () =>
        inheritedDocument?.documentElement.classList.contains('dark') ?? false,
      [inheritedDocument],
    ),
    () => false,
  );
  // Same-origin display inheritance does not carry auth/session or preferences.
  const resolved = inheritedDocument
    ? inheritedDarkMode
      ? 'dark'
      : 'light'
    : resolveThemePreference(preference, systemDarkMode);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark');
  }, [resolved]);
  return resolved;
}
