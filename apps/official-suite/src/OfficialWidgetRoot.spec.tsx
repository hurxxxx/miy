import { act, cleanup, render, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import OfficialWidgetRoot from './OfficialWidgetRoot';

const auth = vi.hoisted(() => ({
  token: null,
  user: {
    id: 'synthetic-theme-user',
    theme_preference: 'dark' as 'light' | 'dark' | 'system',
  },
}));
vi.mock('@miy/platform-web/auth-context', () => ({ useAuth: () => auth }));
vi.mock('@miy/web-official-suite-bridge', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  RequireAuth: ({ children }: { children: ReactNode }) => children,
  DefaultShellRealtimeProvider: ({ children }: { children: ReactNode }) =>
    children,
  useAppsBootstrap: () => ({ data: null, error: null, loading: false }),
}));
vi.mock('./OfficialPersonalWidgetHost', () => ({
  ShellPersonalWidgetHost: () => <div>Widget surface</div>,
}));

let media: EventTarget & { matches: boolean };
beforeEach(() => {
  media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => media),
  );
  auth.user.theme_preference = 'dark';
  document.documentElement.classList.remove('dark');
  window.history.replaceState(null, '', '/official-suite/widgets');
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove('dark');
  window.history.replaceState(null, '', '/');
});

it('applies user and live system theme when the widget is a top-level document', () => {
  const root = render(<OfficialWidgetRoot />);
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  auth.user.theme_preference = 'light';
  root.rerender(<OfficialWidgetRoot />);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
  auth.user.theme_preference = 'system';
  root.rerender(<OfficialWidgetRoot />);
  act(() => {
    media.matches = true;
    media.dispatchEvent(new Event('change'));
  });
  expect(document.documentElement.classList.contains('dark')).toBe(true);
});

it('follows same-origin parent theme changes without waiting for another auth bootstrap', async () => {
  const parentDocument = document.implementation.createHTMLDocument();
  parentDocument.documentElement.classList.add('dark');
  vi.spyOn(window, 'parent', 'get').mockReturnValue({
    document: parentDocument,
    location: { origin: window.location.origin },
  } as Window);
  auth.user.theme_preference = 'light';
  render(<OfficialWidgetRoot />);
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  parentDocument.documentElement.classList.remove('dark');
  await waitFor(() =>
    expect(document.documentElement.classList.contains('dark')).toBe(false),
  );
  parentDocument.documentElement.classList.add('dark');
  await waitFor(() =>
    expect(document.documentElement.classList.contains('dark')).toBe(true),
  );
});

it('uses its own user preference when the parent is cross-origin or inaccessible', () => {
  const parent = {
    get location() {
      throw new DOMException('Synthetic foreign parent', 'SecurityError');
    },
  };
  vi.spyOn(window, 'parent', 'get').mockReturnValue(parent as Window);
  const root = render(<OfficialWidgetRoot />);
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  auth.user.theme_preference = 'light';
  root.rerender(<OfficialWidgetRoot />);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
});
