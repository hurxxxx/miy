import {
  AuthContext as SharedAuthContext,
  useAuth as useSharedAuth,
} from '@miy/platform-web/auth-context';
import {
  ApiRequestError as SharedApiRequestError,
  apiFetchJson as sharedApiFetchJson,
  jsonHeaders as sharedJsonHeaders,
} from '@miy/platform-web/api-client';
import { readStoredTimeZonePreference } from '@miy/platform-web/time/time-utils';
import { DiagramsView } from '@miy/official-suite-web/diagrams';
import { listDiagramsHub } from '@miy/official-suite-web/diagrams/api/diagrams-api';
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createAuthUser } from '../../../tests/fixtures/company';
import { ApiRequestError } from '../api/client';
import { i18n } from '../i18n';
import {
  AuthApiError,
  getBootstrapStatus,
  getCurrentUser,
  logout,
} from './auth-api';
import { AuthContext, useAuth } from './auth-context';
import { AuthProvider } from './auth-provider';
import { AUTH_TOKEN_STORAGE_KEY } from './auth-storage';
import { RequireAuth } from './require-auth';

vi.mock('./auth-api', async (original) => ({
  ...(await original<typeof import('./auth-api')>()),
  getBootstrapStatus: vi.fn(),
  getCurrentUser: vi.fn(),
  logout: vi.fn(),
}));
vi.mock(
  '@miy/official-suite-web/diagrams/api/diagrams-api',
  async (original) => ({
    ...(await original<
      typeof import('@miy/official-suite-web/diagrams/api/diagrams-api')
    >()),
    listDiagramsHub: vi.fn().mockResolvedValue({
      items: [],
      total: 0,
      view: 'all',
      page: 1,
      page_size: 200,
    }),
  }),
);
vi.mock('./desktop-session-sync', () => ({
  syncDesktopLoginSession: vi.fn().mockResolvedValue(undefined),
  syncDesktopLogoutSession: vi.fn(),
}));
vi.mock('../analytics/matomo', () => ({
  identifyMatomoUser: vi.fn(),
  clearMatomoUser: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, 'owned-session');
  vi.mocked(getBootstrapStatus).mockResolvedValue({
    requires_setup: false,
    dev_admin_login_available: false,
    dev_login_accounts: [],
  });
  vi.mocked(getCurrentUser).mockResolvedValue(
    createAuthUser({
      locale: 'en-US',
      time_zone: 'UTC',
      date_format: 'iso',
      must_change_password: false,
    }),
  );
  vi.mocked(logout).mockResolvedValue(undefined);
});
afterEach(async () => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  await i18n.changeLanguage('ko-KR');
});

function Consumer() {
  const shared = useSharedAuth();
  const legacy = useAuth();
  return (
    <>
      <output>{shared === legacy ? shared.status : 'different context'}</output>
      <button onClick={() => void shared.logout()}>Sign out</button>
      <button
        onClick={() => void shared.refreshAccessUser().catch(() => undefined)}
      >
        Refresh access
      </button>
    </>
  );
}

it('shares the original provider state and removes protected UI immediately on logout', async () => {
  expect(AuthContext).toBe(SharedAuthContext);
  render(
    <MemoryRouter initialEntries={['/apps/diagrams']}>
      <AuthProvider>
        <Consumer />
        <Routes>
          <Route
            path="/apps/diagrams"
            element={
              <RequireAuth>
                <p>Protected business UI</p>
                <DiagramsView />
              </RequireAuth>
            }
          />
          <Route path="/login" element={<p>Login screen</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  await screen.findByText('Protected business UI');
  expect(screen.getByText('authenticated')).toBeTruthy();
  expect(getCurrentUser).toHaveBeenCalledWith('owned-session');
  await waitFor(() =>
    expect(listDiagramsHub).toHaveBeenCalledWith(
      'owned-session',
      expect.any(Object),
    ),
  );
  expect(sharedJsonHeaders('owned-session')).toMatchObject({
    'X-MIY-Locale': 'en-US',
  });
  expect(readStoredTimeZonePreference()).toBe('UTC');
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByText('Login screen');
  expect(screen.queryByText('Protected business UI')).toBeNull();
  expect(screen.getByText('unauthenticated')).toBeTruthy();
  expect(window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBeNull();
  await waitFor(() => expect(logout).toHaveBeenCalledWith('owned-session'));
});

it('uses the existing initialized locale for the missing-provider error', async () => {
  await i18n.changeLanguage('en-US');
  expect(() => renderHook(() => useSharedAuth())).toThrow(
    i18n.t('auth:errors.authProviderMissing'),
  );
});

it('preserves error class identity across old and shared API clients', async () => {
  expect(ApiRequestError).toBe(SharedApiRequestError);
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session expired' }), {
        status: 401,
      }),
    ),
  );
  await expect(
    sharedApiFetchJson('/api/current-user', 'expired'),
  ).rejects.toBeInstanceOf(ApiRequestError);
});

it.each([401, 403])(
  'removes protected business UI when shared access refresh receives %s',
  async (status) => {
    render(
      <MemoryRouter initialEntries={['/apps/diagrams']}>
        <AuthProvider>
          <Consumer />
          <Routes>
            <Route
              path="/apps/diagrams"
              element={
                <RequireAuth>
                  <p>Protected business UI</p>
                  <DiagramsView />
                </RequireAuth>
              }
            />
            <Route path="/login" element={<p>Login screen</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
    await screen.findByText('Protected business UI');
    vi.mocked(getCurrentUser).mockRejectedValueOnce(
      new AuthApiError(status, 'Access withdrawn'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Refresh access' }));
    await screen.findByText('Login screen');
    expect(screen.queryByText('Protected business UI')).toBeNull();
    expect(screen.getByText('unauthenticated')).toBeTruthy();
    expect(window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBeNull();
    expect(getCurrentUser).toHaveBeenLastCalledWith('owned-session');
  },
);
