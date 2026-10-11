import { createAuthUser } from '../../../tests/fixtures/company';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AuthSessionResponse, AuthUser } from './auth-api';
import { AUTH_TOKEN_STORAGE_KEY } from './auth-storage';
import { AuthProvider, useAuth } from './auth-provider';
import type { AuthContextValue } from './auth-context';

const apiMocks = vi.hoisted(() => ({
  getBootstrapStatus: vi.fn(),
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  updatePreferences: vi.fn(),
}));

vi.mock('./auth-api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./auth-api')>()),
  getBootstrapStatus: apiMocks.getBootstrapStatus,
  getCurrentUser: apiMocks.getCurrentUser,
  login: apiMocks.login,
  logout: apiMocks.logout,
  updatePreferences: apiMocks.updatePreferences,
}));

vi.mock('./desktop-session-sync', () => ({
  syncDesktopLoginSession: vi.fn().mockResolvedValue(undefined),
  syncDesktopLogoutSession: vi.fn(),
}));

vi.mock('@/src/platform/analytics/matomo', () => ({
  clearMatomoUser: vi.fn(),
  identifyMatomoUser: vi.fn(),
}));

function user(overrides: Partial<AuthUser> = {}): AuthUser {
  return createAuthUser({
    app_bar_layout: { pinned_app_ids: [] },
    date_format: 'korean',
    display_name: 'Member',
    email: 'member@miy.local',
    full_name: 'miy Member',
    id: 'user-1',
    last_login_at: null,
    locale: 'ko-KR',
    login_id: 'member',
    must_change_password: false,
    status: 'active',
    system_roles: [],
    group_ids: [],
    managed_organization_unit_ids: [],
    theme_preference: 'system',
    time_zone: 'Asia/Seoul',
    ...overrides,
  });
}

function session(): AuthSessionResponse {
  return { token: 'login-token', user: user() };
}

function AuthHarness() {
  const auth = useAuth();
  return (
    <div>
      <p>{auth.status}</p>
      <p data-testid="access-projection">
        {auth.user?.locale ?? 'none'}|{auth.user?.group_ids.join(',') ?? 'none'}
      </p>
      <button
        onClick={() =>
          void auth.login({ login_id: 'member', password: 'password123' })
        }
        type="button"
      >
        login
      </button>
      <button onClick={() => void auth.logout()} type="button">
        logout
      </button>
      <button onClick={() => void auth.refreshAccessUser()} type="button">
        refresh access
      </button>
      <button
        onClick={() => void auth.updatePreferences({ locale: 'en-US' })}
        type="button"
      >
        update preferences
      </button>
    </div>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  apiMocks.getBootstrapStatus.mockResolvedValue({
    dev_admin_login_available: false,
    dev_login_accounts: [],
    requires_setup: false,
  });
  apiMocks.login.mockResolvedValue(session());
  apiMocks.logout.mockReset().mockResolvedValue(undefined);
  apiMocks.getCurrentUser.mockReset();
  apiMocks.updatePreferences.mockReset();
});
afterEach(cleanup);

let currentAuth: AuthContextValue;
function SessionProbe() {
  currentAuth = useAuth();
  return <p>{currentAuth.status}</p>;
}
function currentGuard() {
  const guard = currentAuth.isSessionCurrent;
  if (!guard) throw new Error('Missing live-session snapshot');
  return guard;
}
async function authenticatedProvider() {
  const rendered = render(
    <AuthProvider>
      <SessionProbe />
    </AuthProvider>,
  );
  await screen.findByText('unauthenticated');
  await act(async () =>
    currentAuth.login({ login_id: 'member', password: 'password123' }),
  );
  expect(currentGuard()()).toBe(true);
  return rendered;
}

describe('AuthProvider credential snapshots', () => {
  it('retires the previous document session before verifying a stored session change', async () => {
    await authenticatedProvider();
    const previous = currentGuard();
    let verify!: (value: AuthUser) => void;
    apiMocks.getCurrentUser.mockImplementationOnce(
      () =>
        new Promise<AuthUser>((resolve) => {
          verify = resolve;
        }),
    );
    act(() => {
      window.localStorage.setItem(
        AUTH_TOKEN_STORAGE_KEY,
        'another-document-token',
      );
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: AUTH_TOKEN_STORAGE_KEY,
          storageArea: window.localStorage,
        }),
      );
      expect(previous()).toBe(false);
    });
    expect(apiMocks.getCurrentUser).toHaveBeenCalledWith(
      'another-document-token',
    );
    expect(currentGuard()()).toBe(false);
    await act(async () => {
      verify(user());
    });
    await waitFor(() =>
      expect(currentAuth.token).toBe('another-document-token'),
    );
    expect(previous()).toBe(false);
    expect(currentGuard()()).toBe(true);
  });

  it.each(['same token', 'rotated token', 'logout then same token'])(
    'invalidates the previous snapshot synchronously for %s',
    async (boundary) => {
      await authenticatedProvider();
      const previous = currentGuard();
      act(() => {
        if (boundary === 'logout then same token') {
          void currentAuth.logout();
          expect(previous()).toBe(false);
        }
        currentAuth.switchSession({
          ...session(),
          token: boundary === 'rotated token' ? 'rotated-token' : 'login-token',
        });
        expect(previous()).toBe(false);
      });
      const installed = currentGuard();
      expect(installed).not.toBe(previous);
      expect(installed()).toBe(true);
      act(() => {
        currentAuth.switchSession(session());
        expect(installed()).toBe(false);
        expect(previous()).toBe(false);
      });
      expect(currentGuard()()).toBe(true);
    },
  );

  it('does not revive an old snapshot after accepted same-token login', async () => {
    await authenticatedProvider();
    const previous = currentGuard();
    await act(async () =>
      currentAuth.login({ login_id: 'member', password: 'password123' }),
    );
    expect(previous()).toBe(false);
    expect(currentGuard()).not.toBe(previous);
    expect(currentGuard()()).toBe(true);
  });

  it('preserves a snapshot through same-session bootstrap, access, and preferences refresh', async () => {
    await authenticatedProvider();
    const snapshot = currentGuard();
    let finish!: (value: AuthUser) => void;
    apiMocks.getCurrentUser.mockImplementationOnce(
      () =>
        new Promise<AuthUser>((resolve) => {
          finish = resolve;
        }),
    );
    let refreshing!: Promise<void>;
    act(() => {
      refreshing = currentAuth.refreshSession();
    });
    expect(screen.getByText('bootstrapping')).toBeTruthy();
    expect(snapshot()).toBe(true);
    expect(currentGuard()).toBe(snapshot);
    await act(async () => {
      finish(user({ group_ids: ['current-group'] }));
      await refreshing;
    });
    apiMocks.getCurrentUser.mockResolvedValue(user({ group_ids: [] }));
    await act(async () => {
      await currentAuth.refreshAccessUser();
    });
    apiMocks.updatePreferences.mockResolvedValue(user({ locale: 'en-US' }));
    await act(async () => currentAuth.updatePreferences({ locale: 'en-US' }));
    expect(currentGuard()).toBe(snapshot);
    expect(snapshot()).toBe(true);
  });

  it('invalidates snapshots when current-session verification rejects the credential', async () => {
    await authenticatedProvider();
    const snapshot = currentGuard();
    apiMocks.getCurrentUser.mockResolvedValue(null);
    await act(async () => currentAuth.refreshSession());
    expect(snapshot()).toBe(false);
    expect(currentGuard()()).toBe(false);
  });

  it('does not revive a snapshot when the provider unmounts and remounts with the same credential', async () => {
    const rendered = await authenticatedProvider();
    const previous = currentGuard();
    rendered.unmount();
    expect(previous()).toBe(false);
    apiMocks.getCurrentUser.mockResolvedValue(user());
    render(
      <AuthProvider>
        <SessionProbe />
      </AuthProvider>,
    );
    await screen.findByText('authenticated');
    expect(previous()).toBe(false);
    expect(currentGuard()()).toBe(true);
  });
});

describe('AuthProvider logout', () => {
  it('removes authenticated content before the server revoke finishes or fails', async () => {
    let rejectLogout!: (reason: unknown) => void;
    apiMocks.logout.mockImplementation(
      () =>
        new Promise<void>((_resolve, reject) => {
          rejectLogout = reject;
        }),
    );

    render(
      <AuthProvider>
        <AuthHarness />
      </AuthProvider>,
    );
    await screen.findByText('unauthenticated');

    fireEvent.click(screen.getByRole('button', { name: 'login' }));
    await screen.findByText('authenticated');
    expect(window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBe(
      'login-token',
    );

    fireEvent.click(screen.getByRole('button', { name: 'logout' }));
    expect(screen.getByText('unauthenticated')).toBeTruthy();
    expect(window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBeNull();
    expect(apiMocks.logout).toHaveBeenCalledWith('login-token');

    rejectLogout(new Error('server unavailable'));
    await waitFor(() =>
      expect(screen.getByText('unauthenticated')).toBeTruthy(),
    );
  });
});

describe('AuthProvider concurrent account updates', () => {
  it.each([
    { previous: ['group-revoked'], current: [] },
    { previous: [], current: ['group-granted'] },
  ])(
    'keeps current group access $current when older preferences resolve',
    async ({ previous, current }) => {
      let resolvePreferences!: (value: AuthUser) => void;
      apiMocks.updatePreferences.mockImplementation(
        () =>
          new Promise<AuthUser>((resolve) => {
            resolvePreferences = resolve;
          }),
      );
      apiMocks.login.mockResolvedValue({
        token: 'login-token',
        user: user({ group_ids: previous }),
      });
      apiMocks.getCurrentUser.mockResolvedValue(user({ group_ids: current }));

      render(
        <AuthProvider>
          <AuthHarness />
        </AuthProvider>,
      );
      await screen.findByText('unauthenticated');
      fireEvent.click(screen.getByRole('button', { name: 'login' }));
      await screen.findByText('authenticated');

      fireEvent.click(
        screen.getByRole('button', { name: 'update preferences' }),
      );
      fireEvent.click(screen.getByRole('button', { name: 'refresh access' }));
      await waitFor(() =>
        expect(screen.getByTestId('access-projection').textContent).toBe(
          `ko-KR|${current.join(',')}`,
        ),
      );

      resolvePreferences(user({ locale: 'en-US', group_ids: previous }));
      await waitFor(() =>
        expect(screen.getByTestId('access-projection').textContent).toBe(
          `en-US|${current.join(',')}`,
        ),
      );
    },
  );
});
