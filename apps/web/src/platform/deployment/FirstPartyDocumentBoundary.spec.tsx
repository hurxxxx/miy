import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { BrowserRouter, useNavigate } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { FirstPartyDocumentBoundary } from './FirstPartyDocumentBoundary';
import {
  reloadFirstPartyDocument,
  type FirstPartyUiOwner,
} from './first-party-navigation';

vi.mock('./first-party-navigation', async (original) => ({
  ...(await original<typeof import('./first-party-navigation')>()),
  reloadFirstPartyDocument: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.mocked(reloadFirstPartyDocument).mockClear();
  window.history.replaceState(null, '', '/');
});

it.each([
  [
    'official',
    '/apps/meeting',
    '/apps/chatbot?conversationId=synthetic#draft',
    false,
  ],
  [
    'official',
    '/apps/docs',
    '/apps/chatbot?conversationId=synthetic#draft',
    true,
  ],
  [
    'platform',
    '/apps/chatbot',
    '/apps/docs/page?selected=synthetic#draft',
    false,
  ],
  ['platform', '/apps/home', '/apps/pms?selected=synthetic#draft', true],
] as const)(
  'reloads %s document crossings while retaining router state (%s)',
  (owner, from, to, replace) => {
    const draft = {
      aiDraft: 'Synthetic draft',
      aiDraftSourceKey: 'synthetic-insight',
      aiDraftOrigin: 'meeting_insight',
    };
    window.history.replaceState(null, '', from);
    const previousLength = window.history.length;
    function Navigation() {
      const navigate = useNavigate();
      return (
        <button onClick={() => navigate(to, { state: draft, replace })}>
          Open
        </button>
      );
    }
    render(
      <BrowserRouter>
        <FirstPartyDocumentBoundary owner={owner as FirstPartyUiOwner}>
          <Navigation />
        </FirstPartyDocumentBoundary>
      </BrowserRouter>,
    );
    expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(reloadFirstPartyDocument).toHaveBeenCalledOnce();
    expect(
      `${window.location.pathname}${window.location.search}${window.location.hash}`,
    ).toBe(to);
    expect(window.history.state.usr).toEqual(draft);
    expect(window.history.state.key).toEqual(expect.any(String));
    expect(window.history.length).toBe(previousLength + (replace ? 0 : 1));
    expect(screen.queryByRole('button', { name: 'Open' })).toBeNull();
  },
);

it('keeps same-owner programmatic navigation inside its current document', () => {
  window.history.replaceState(null, '', '/apps/docs');
  function Navigation() {
    const navigate = useNavigate();
    return (
      <button
        onClick={() => navigate('/apps/docs/page?selected=synthetic#content')}
      >
        Open
      </button>
    );
  }
  render(
    <BrowserRouter>
      <FirstPartyDocumentBoundary owner="official">
        <Navigation />
      </FirstPartyDocumentBoundary>
    </BrowserRouter>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Open' }));
  expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Open' })).toBeTruthy();
});
