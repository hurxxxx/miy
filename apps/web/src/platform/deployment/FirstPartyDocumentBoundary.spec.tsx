import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { useState } from 'react';
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom';
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
  vi.useRealTimers();
});

it.each([
  ['official', '/apps/docs', false],
  ['official', '/apps/docs', true],
  ['widget', '/official-suite/widgets', false],
  ['widget', '/official-suite/widgets', true],
] as const)(
  'retains the mounted %s UI at %s while saves are pending (cancel=%s)',
  async (owner, from, cancel) => {
    vi.useFakeTimers();
    window.history.replaceState(null, '', from);
    const handoff = { aiDraft: 'Synthetic handoff' };
    function PendingNavigation() {
      const navigate = useNavigate();
      const visibleLocation = useLocation();
      const [body, setBody] = useState('');
      const [pending, setPending] = useState(true);
      return (
        <>
          <input
            aria-label="Draft"
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
          <div data-miy-pending-save={pending ? 'true' : undefined} />
          <output aria-label="Owned location">
            {visibleLocation.pathname}
          </output>
          <button
            onClick={() =>
              navigate('/apps/chatbot?draft=synthetic#handoff', {
                state: handoff,
              })
            }
          >
            Cross
          </button>
          <button onClick={() => setPending(false)}>Saved</button>
          <button onClick={() => navigate(from, { replace: true })}>
            Cancel
          </button>
        </>
      );
    }
    render(
      <BrowserRouter>
        <FirstPartyDocumentBoundary owner={owner}>
          <PendingNavigation />
        </FirstPartyDocumentBoundary>
      </BrowserRouter>,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Draft' }), {
      target: { value: 'Unsaved input' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Cross' }));
    await act(async () => vi.advanceTimersByTime(300));
    expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('Unsaved input')).toBeTruthy();
    expect(screen.getByLabelText('Owned location').textContent).toBe(from);
    expect(window.history.state.usr).toEqual(handoff);
    if (cancel) fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Saved' }));
    await act(async () => vi.advanceTimersByTime(100));
    expect(reloadFirstPartyDocument).toHaveBeenCalledTimes(cancel ? 0 : 1);
    expect(screen.getByDisplayValue('Unsaved input')).toBeTruthy();
    expect(window.location.pathname).toBe(cancel ? from : '/apps/chatbot');
  },
);

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
    // Keep the old owner/unload protection mounted; the new owner never renders.
    expect(screen.getByRole('button', { name: 'Open' })).toBeTruthy();
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
