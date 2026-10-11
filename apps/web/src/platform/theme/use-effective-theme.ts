import { useSyncExternalStore } from 'react';

function snapshot(): 'light' | 'dark' {
  return typeof document !== 'undefined' &&
    document.documentElement.classList.contains('dark')
    ? 'dark'
    : 'light';
}

function subscribe(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class'],
  });
  return () => observer.disconnect();
}

/** Read the shell's effective theme; preference/system resolution remains shell-owned. */
export function useEffectiveTheme(): 'light' | 'dark' {
  return useSyncExternalStore(subscribe, snapshot, () => 'light');
}
