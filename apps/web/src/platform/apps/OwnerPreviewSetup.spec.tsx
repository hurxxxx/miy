import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import OwnerPreviewSetup from './OwnerPreviewSetup';
import {
  ownerPreviewApiPath,
  ownerPreviewSettingsPath,
  parseOwnerPreview,
  type OwnerPreview,
} from './owner-preview';

const auth = vi.hoisted(() => ({
  token: 'owner-login' as string | null,
  user: { id: 'owner' } as { id: string } | null,
}));
const success = vi.hoisted(() => vi.fn());
vi.mock('@/src/platform/auth/auth-provider', () => ({ useAuth: () => auth }));
vi.mock('@/src/platform/api/client', async (original) => ({
  ...(await original<typeof import('@/src/platform/api/client')>()),
  apiFetchJson: vi.fn(),
}));
vi.mock('@miy/ui', async (original) => ({
  ...(await original<typeof import('@miy/ui')>()),
  useFeedback: () => ({ success }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const label = (key: string) => `independentApps.previewSetup.${key}`;
const installationId = 'b0000000-0000-4000-8000-000000000001';
const snapshot: OwnerPreview = {
  schema_version: 1,
  app_id: 'private-notes',
  installation_id: installationId,
  owner_user_id: 'owner',
  display_name: 'Private notes',
  origin: 'https://notes.example.test',
  generation: 1,
  definition_digest: `sha256:${'a'.repeat(64)}`,
  source_revision: 'b'.repeat(40),
  runtime_profile: 'web-api-postgres-v1',
  requested_permissions: ['identity:read', 'data:read', 'data:write'],
  granted_permissions: [],
  enabled: false,
  company_enabled: true,
  can_configure: true,
  unavailable_reason: null,
};
function view() {
  return (
    <StrictMode>
      <MemoryRouter
        initialEntries={[
          ownerPreviewSettingsPath(snapshot.app_id, installationId),
        ]}
      >
        <Routes>
          <Route
            path="/apps/:appId/installed/:installationId/setup"
            element={<OwnerPreviewSetup />}
          />
          <Route path="/elsewhere" element={<p>Elsewhere</p>} />
        </Routes>
        <Link to="/elsewhere">Leave</Link>
      </MemoryRouter>
    </StrictMode>
  );
}
const writes = () =>
  vi
    .mocked(apiFetchJson)
    .mock.calls.filter((call) => call[2]?.method === 'PATCH');
function pendingValue() {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function editAndSave() {
  await screen.findByText(snapshot.display_name);
  fireEvent.click(screen.getByLabelText(label('enabled')));
  fireEvent.click(screen.getByLabelText(label('identity')));
  fireEvent.click(screen.getByRole('button', { name: label('save') }));
}
beforeEach(() => {
  auth.token = 'owner-login';
  auth.user = { id: 'owner' };
  success.mockReset();
  vi.mocked(apiFetchJson).mockReset();
  vi.mocked(apiFetchJson).mockResolvedValue(snapshot);
});
afterEach(() => vi.useRealTimers());

it('shows selected-file access distinctly on a basic app and sends only explicitly chosen grants', async () => {
  const fileSnapshot: OwnerPreview = {
    ...snapshot,
    runtime_profile: 'web-api-v1',
    requested_permissions: ['identity:read', 'files:read-selected'],
  };
  vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
    init?.method === 'PATCH'
      ? {
          ...fileSnapshot,
          generation: 2,
          granted_permissions: ['files:read-selected'],
        }
      : fileSnapshot,
  );
  render(view());
  const permission = await screen.findByLabelText(label('selectedFileRead'));
  expect(screen.queryByLabelText(label('dataWrite'))).toBeNull();
  expect(writes()).toHaveLength(0);
  fireEvent.click(permission);
  fireEvent.click(screen.getByRole('button', { name: label('save') }));
  await waitFor(() => expect(success).toHaveBeenCalledWith(label('saved')));
  expect(JSON.parse(String(writes()[0][2]?.body)).granted_permissions).toEqual([
    'files:read-selected',
  ]);
});

it('accepts all four explicit permissions in the PostgreSQL profile without granting them implicitly', () => {
  const value = {
    ...snapshot,
    requested_permissions: [
      ...snapshot.requested_permissions,
      'files:read-selected',
    ],
  };
  expect(
    parseOwnerPreview(value, {
      appId: snapshot.app_id,
      installationId,
      userId: 'owner',
    }).granted_permissions,
  ).toEqual([]);
});

it('loads in StrictMode without writing, then sends only a bounded CAS policy update', async () => {
  const result = {
    ...snapshot,
    generation: 2,
    enabled: true,
    granted_permissions: ['identity:read'],
  };
  vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
    init?.method === 'PATCH' ? result : snapshot,
  );
  render(view());
  await screen.findByText(snapshot.display_name);
  expect(writes()).toHaveLength(0);
  expect(
    screen.getByRole('button', { name: label('save') }).matches(':disabled'),
  ).toBe(true);
  await editAndSave();
  await waitFor(() => expect(success).toHaveBeenCalledWith(label('saved')));
  expect(writes()).toHaveLength(1);
  expect(writes()[0][0]).toBe(
    ownerPreviewApiPath(snapshot.app_id, installationId),
  );
  expect(JSON.parse(writes()[0][2]?.body as string)).toEqual({
    expected_generation: 1,
    expected_definition_digest: snapshot.definition_digest,
    expected_source_revision: snapshot.source_revision,
    enabled: true,
    granted_permissions: ['identity:read'],
  });
});

it('does not duplicate a pending save and recovers a lost response by GET only', async () => {
  const pending = pendingValue();
  let current = snapshot;
  vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
    init?.method === 'PATCH' ? pending.promise : current,
  );
  render(view());
  await editAndSave();
  fireEvent.click(screen.getByRole('button', { name: label('save') }));
  expect(writes()).toHaveLength(1);
  await act(async () => pending.reject(new Error('response lost')));
  expect(await screen.findByText(label('unknown'))).toBeTruthy();
  expect(
    screen.getByRole('button', { name: label('save') }).matches(':disabled'),
  ).toBe(true);
  current = {
    ...snapshot,
    generation: 2,
    enabled: true,
    granted_permissions: ['identity:read'],
  };
  fireEvent.click(screen.getByRole('button', { name: label('refresh') }));
  expect(await screen.findByText(label('observed'))).toBeTruthy();
  expect(
    (screen.getByLabelText(label('enabled')) as HTMLInputElement).checked,
  ).toBe(true);
  expect(writes()).toHaveLength(1);
  expect(success).not.toHaveBeenCalled();
});

it('requires fresh settings after a conflict and uses the newly read generation on explicit retry', async () => {
  let current = snapshot;
  vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) => {
    if (init?.method === 'PATCH') throw new ApiRequestError(409, 'conflict');
    return current;
  });
  render(view());
  await editAndSave();
  expect(await screen.findByText(label('changed'))).toBeTruthy();
  expect(
    screen.getByRole('button', { name: label('save') }).matches(':disabled'),
  ).toBe(true);
  current = { ...snapshot, generation: 3 };
  fireEvent.click(screen.getByRole('button', { name: label('refresh') }));
  await waitFor(() =>
    expect(
      (screen.getByLabelText(label('enabled')) as HTMLInputElement).checked,
    ).toBe(false),
  );
  expect(writes()).toHaveLength(1);
  await editAndSave();
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(JSON.parse(writes()[1][2]?.body as string).expected_generation).toBe(
    3,
  );
});

it.each([
  'already_deployed',
  'delivery_in_progress',
  'build_in_progress',
  'already_verified',
  'company_disabled',
  'origin_configuration_required',
  'invalid_origin',
] as const)('renders %s as read-only without submitting', async (reason) => {
  vi.mocked(apiFetchJson).mockResolvedValue({
    ...snapshot,
    can_configure: false,
    unavailable_reason: reason,
  });
  render(view());
  await screen.findByText(snapshot.display_name);
  expect(screen.getByLabelText(label('enabled')).matches(':disabled')).toBe(
    true,
  );
  expect(
    screen.getByRole('button', { name: label('save') }).matches(':disabled'),
  ).toBe(true);
  expect(writes()).toHaveLength(0);
});

it.each(['login', 'leave', 'logout'] as const)(
  'ignores an accepted save completion after %s',
  async (change) => {
    const pending = pendingValue();
    vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
      init?.method === 'PATCH' ? pending.promise : snapshot,
    );
    const rendered = render(view());
    await editAndSave();
    if (change === 'leave')
      fireEvent.click(screen.getByRole('link', { name: 'Leave' }));
    else {
      auth.token = change === 'logout' ? null : 'new-login';
      rendered.rerender(view());
    }
    await act(async () =>
      pending.resolve({
        ...snapshot,
        generation: 2,
        enabled: true,
        granted_permissions: ['identity:read'],
      }),
    );
    expect(success).not.toHaveBeenCalled();
    if (change !== 'login')
      expect(screen.queryByText(snapshot.display_name)).not.toBeTruthy();
    else
      expect(
        (screen.getByLabelText(label('enabled')) as HTMLInputElement).checked,
      ).toBe(false);
    expect(writes()).toHaveLength(1);
  },
);

it.each([{ granted_permissions: ['data:write'] }, { generation: 1 }])(
  'rejects a mismatched PATCH response %j as unknown without showing success',
  async (change) => {
    vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
      init?.method === 'PATCH'
        ? {
            ...snapshot,
            generation: 2,
            enabled: true,
            granted_permissions: ['identity:read'],
            ...change,
          }
        : snapshot,
    );
    render(view());
    await editAndSave();
    expect(await screen.findByText(label('unknown'))).toBeTruthy();
    expect(success).not.toHaveBeenCalled();
    expect(writes()).toHaveLength(1);
  },
);

it('bounds a hung save even when transport ignores AbortSignal', async () => {
  const pending = pendingValue();
  vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) =>
    init?.method === 'PATCH' ? pending.promise : snapshot,
  );
  render(view());
  await screen.findByText(snapshot.display_name);
  vi.useFakeTimers();
  const timeout = new AbortController();
  const timeoutStub = vi
    .spyOn(AbortSignal, 'timeout')
    .mockReturnValue(timeout.signal);
  fireEvent.click(screen.getByLabelText(label('enabled')));
  fireEvent.click(screen.getByRole('button', { name: label('save') }));
  expect(timeoutStub).toHaveBeenCalledWith(30_000);
  await act(async () => timeout.abort());
  expect(screen.getByText(label('unknown'))).toBeTruthy();
  expect(writes()).toHaveLength(1);
  timeoutStub.mockRestore();
});

it.each([
  { owner_user_id: 'another-owner' },
  { app_id: 'another-app' },
  { installation_id: 'wrong' },
  { schema_version: true },
  { enabled: 'true' },
  { origin: 'https://notes.example.test/path' },
  { granted_permissions: ['admin:all'] },
  { granted_permissions: ['identity:read', 'identity:read'] },
  { generation: 0 },
  { can_configure: true, unavailable_reason: 'already_deployed' },
  { source_revision: 'x' },
  { runtime_profile: 'web-api-v1' },
])('rejects substituted or malformed observed settings %j', (change) => {
  expect(() =>
    parseOwnerPreview(
      { ...snapshot, ...change },
      { appId: snapshot.app_id, installationId, userId: 'owner' },
    ),
  ).toThrow();
});
