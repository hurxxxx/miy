// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { ThemePreference } from '../auth-types.js';
import { DARK_MODE_QUERY, useDocumentTheme } from './document-theme';

let media: EventTarget & { matches: boolean };
beforeEach(() => {
  media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => media),
  );
  document.documentElement.className = 'existing-shell-class';
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.className = '';
});

function Theme({
  preference,
  inherited,
}: {
  preference?: ThemePreference;
  inherited?: Document;
}) {
  const theme = useDocumentTheme(preference, inherited);
  return <output>{theme}</output>;
}

it('keeps normal shells aligned with user preference and live system changes', () => {
  const root = render(<Theme />);
  expect(window.matchMedia).toHaveBeenCalledWith(DARK_MODE_QUERY);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
  act(() => {
    media.matches = true;
    media.dispatchEvent(new Event('change'));
  });
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  root.rerender(<Theme preference="light" />);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
  root.rerender(<Theme preference="dark" />);
  act(() => {
    media.matches = false;
    media.dispatchEvent(new Event('change'));
  });
  expect(document.documentElement.classList.contains('dark')).toBe(true);
  expect(
    document.documentElement.classList.contains('existing-shell-class'),
  ).toBe(true);
  root.rerender(<Theme preference="system" />);
  expect(document.documentElement.classList.contains('dark')).toBe(false);
});

it('removes native media and inherited-document subscriptions when unmounted', () => {
  const inherited = document.implementation.createHTMLDocument();
  const remove = vi.spyOn(media, 'removeEventListener');
  const disconnect = vi.spyOn(MutationObserver.prototype, 'disconnect');
  const root = render(<Theme inherited={inherited} />);
  root.unmount();
  expect(remove).toHaveBeenCalledWith('change', expect.any(Function));
  expect(disconnect).toHaveBeenCalledOnce();
});
