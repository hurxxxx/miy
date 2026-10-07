import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import IndependentAppRegistration from './IndependentAppRegistration';
import { parseRegistrationDraft } from './independent-app-registration';

vi.mock('@/src/platform/api/client', async (original) => ({
  ...(await original<typeof import('@/src/platform/api/client')>()),
  apiFetchJson: vi.fn(),
}));
const auth = vi.hoisted(() => ({
  token: 'synthetic-owner-token',
  user: { id: 'owner-one' },
}));
vi.mock('@/src/platform/auth/auth-provider', () => ({ useAuth: () => auth }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const label = (key: string) => `independentApps.registration.${key}`;
const operation = 'a0000000-0000-4000-8000-000000000001';
const draft = {
  schema_version: 1,
  project_id: 'source-project',
  binding_version: 1,
  app_id: 'notes-app',
  source_revision: 'a'.repeat(40),
  source_manifest_digest: `sha256:${'1'.repeat(64)}`,
  definition_digest: `sha256:${'2'.repeat(64)}`,
  definition: {
    app_id: 'notes-app',
    schema_version: 1,
    ownership: 'personal',
    sdk_version: 1,
    display: { name: '내 메모', icon: 'app-window', translations: {} },
    source: {
      repository: 'https://code.example.test/notes.git',
      directory: '.',
    },
    entrypoints: { ui: '/', api: '/api', health: '/healthz' },
    runtime_profile: 'web-api-postgres-v1',
    requested_permissions: ['identity:read', 'data:read'],
  },
};
const receipt = {
  operation_id: operation,
  app_id: draft.app_id,
  installation_id: 'b0000000-0000-4000-8000-000000000001',
  definition_digest: draft.definition_digest,
  source_revision: draft.source_revision,
  created_at: '2026-10-06T00:00:00Z',
};
function Location() {
  return (
    <>
      <output data-testid="location">{useLocation().search}</output>
      <Link to="/apps/register?operation=a0000000-0000-4000-8000-000000000002">
        Different operation
      </Link>
    </>
  );
}
const view = (entry = '/apps/register') => (
  <StrictMode>
    <MemoryRouter initialEntries={[entry]}>
      <IndependentAppRegistration />
      <Location />
    </MemoryRouter>
  </StrictMode>
);
beforeEach(() => {
  vi.mocked(apiFetchJson).mockReset();
  auth.token = 'synthetic-owner-token';
  auth.user = { id: 'owner-one' };
});
async function loadDraft() {
  const file = new File(['fixture'], 'registration.json', {
    type: 'application/json',
  });
  Object.defineProperty(file, 'text', {
    value: async () => JSON.stringify(draft),
  });
  fireEvent.change(screen.getByLabelText(label('file')), {
    target: { files: [file] },
  });
  await screen.findByText('내 메모');
  fireEvent.change(screen.getByLabelText(label('origin')), {
    target: { value: 'https://notes.dev.example.test' },
  });
}

it('reads a receipt after a lost response without automatically submitting again', async () => {
  vi.mocked(apiFetchJson).mockImplementation(async (path, _token, init) => {
    if (init?.method === 'POST') throw new Error('lost response');
    return { ...receipt, operation_id: path.split('/').at(-1) };
  });
  render(view());
  await loadDraft();
  fireEvent.click(screen.getByRole('button', { name: label('submit') }));
  await screen.findByText(label('unknown'));
  expect(
    (screen.getByLabelText(label('origin')) as HTMLInputElement).disabled,
  ).toBe(true);
  const first = JSON.parse(
    String(vi.mocked(apiFetchJson).mock.calls[0][2]?.body),
  );
  expect(screen.getByTestId('location').textContent).toBe(
    `?operation=${first.operation_id}`,
  );
  expect(screen.getByTestId('location').textContent).not.toContain('token');
  expect(first).toMatchObject({
    definition: draft.definition,
    source_revision: draft.source_revision,
    granted_permissions: [],
  });
  expect(first).not.toHaveProperty('source_manifest_digest');
  fireEvent.click(screen.getByRole('button', { name: label('check') }));
  await screen.findByRole('region', { name: label('receipt') });
  expect(
    vi
      .mocked(apiFetchJson)
      .mock.calls.filter((call) => call[2]?.method === 'POST'),
  ).toHaveLength(1);
});

it('retries an uncertain request with the identical UUID and frozen input', async () => {
  vi.mocked(apiFetchJson)
    .mockImplementationOnce(async () => {
      throw new Error('timeout');
    })
    .mockImplementationOnce(async (_path, _token, init) => ({
      ...receipt,
      operation_id: JSON.parse(String(init?.body)).operation_id,
    }));
  render(view());
  await loadDraft();
  fireEvent.click(screen.getByLabelText(label('profileRead')));
  fireEvent.click(screen.getByRole('button', { name: label('submit') }));
  await screen.findByText(label('unknown'));
  fireEvent.click(screen.getByRole('button', { name: label('retry') }));
  await screen.findByRole('region', { name: label('receipt') });
  const calls = vi.mocked(apiFetchJson).mock.calls;
  expect(calls[1][2]?.body).toBe(calls[0][2]?.body);
  expect(JSON.parse(String(calls[0][2]?.body)).granted_permissions).toEqual([
    'identity:read',
  ]);
});

it('reloads only the receipt and ignores the aborted StrictMode read', async () => {
  const reads: { resolve: (value: unknown) => void; signal: AbortSignal }[] =
    [];
  vi.mocked(apiFetchJson).mockImplementation(
    (_path, _token, init) =>
      new Promise((resolve) => {
        reads.push({ resolve, signal: init?.signal as AbortSignal });
      }),
  );
  render(view(`/apps/register?operation=${operation}`));
  await waitFor(() => expect(reads).toHaveLength(2));
  expect(reads[0].signal.aborted).toBe(true);
  await act(async () => {
    reads[1].resolve(receipt);
  });
  await screen.findByText(receipt.app_id);
  await act(async () => {
    reads[0].resolve({ ...receipt, app_id: 'stale-app' });
  });
  expect(screen.queryByText('stale-app')).toBeNull();
  expect(
    vi
      .mocked(apiFetchJson)
      .mock.calls.every((call) => call[2]?.method === 'GET'),
  ).toBe(true);
});

it('discards drafts and late mutation responses when the signed-in account changes', async () => {
  let complete: (value: unknown) => void = () => {
    throw new Error('Request not sent');
  };
  vi.mocked(apiFetchJson).mockImplementation((_path, _token, init) =>
    init?.method === 'POST'
      ? new Promise((resolve) => {
          complete = resolve;
        })
      : Promise.reject(new ApiRequestError(404, 'not found')),
  );
  const app = render(view());
  await loadDraft();
  fireEvent.click(screen.getByRole('button', { name: label('submit') }));
  await waitFor(() => expect(vi.mocked(apiFetchJson)).toHaveBeenCalledTimes(1));
  auth.token = 'synthetic-other-owner';
  auth.user = { id: 'owner-two' };
  app.rerender(view());
  await screen.findByText(label('notFound'));
  await act(async () => {
    complete(receipt);
  });
  expect(screen.queryByText('내 메모')).toBeNull();
  expect(screen.queryByRole('region', { name: label('receipt') })).toBeNull();
  expect(vi.mocked(apiFetchJson).mock.calls[0][2]?.signal?.aborted).toBe(true);
});

it('rejects oversized, version-mismatched, or non-personal imported drafts before rendering', () => {
  expect(() => parseRegistrationDraft(' '.repeat(262145))).toThrow();
  expect(() =>
    parseRegistrationDraft(JSON.stringify({ ...draft, schema_version: 2 })),
  ).toThrow();
  expect(() =>
    parseRegistrationDraft(
      JSON.stringify({
        ...draft,
        definition: { ...draft.definition, ownership: 'official' },
      }),
    ),
  ).toThrow();
  expect(
    parseRegistrationDraft(JSON.stringify(draft)).definition.display.name,
  ).toBe('내 메모');
});

it('clears the previous receipt when navigation selects a different operation', async () => {
  vi.mocked(apiFetchJson).mockImplementation(async (path) => ({
    ...receipt,
    operation_id: path.split('/').at(-1),
    app_id: path.endsWith('2') ? 'second-app' : receipt.app_id,
  }));
  render(view(`/apps/register?operation=${operation}`));
  await screen.findByText(receipt.app_id);
  fireEvent.click(screen.getByRole('link', { name: 'Different operation' }));
  await screen.findByText('second-app');
  expect(screen.queryByText(receipt.app_id)).toBeNull();
  expect(
    vi
      .mocked(apiFetchJson)
      .mock.calls.every((call) => call[2]?.method === 'GET'),
  ).toBe(true);
});

it.each([
  {},
  { ...receipt, app_id: 'another-app' },
  { ...receipt, definition_digest: `sha256:${'3'.repeat(64)}` },
])(
  'does not confirm an invalid or mismatched successful mutation response: %j',
  async (value) => {
    vi.mocked(apiFetchJson).mockImplementation(async (_path, _token, init) => ({
      ...value,
      operation_id: JSON.parse(String(init?.body)).operation_id,
    }));
    render(view());
    await loadDraft();
    fireEvent.click(screen.getByRole('button', { name: label('submit') }));
    await screen.findByText(label('unknown'));
    expect(screen.queryByRole('region', { name: label('receipt') })).toBeNull();
    expect(
      (screen.getByLabelText(label('origin')) as HTMLInputElement).disabled,
    ).toBe(true);
  },
);

it('rejects a different operation in a successful receipt lookup', async () => {
  vi.mocked(apiFetchJson).mockResolvedValue({
    ...receipt,
    operation_id: 'a0000000-0000-4000-8000-000000000099',
  });
  render(view(`/apps/register?operation=${operation}`));
  await screen.findByText(label('checkFailed'));
  expect(screen.queryByRole('region', { name: label('receipt') })).toBeNull();
});

it('accepts a four-permission draft and gives selected-file access its own unchecked consent label', async () => {
  const extended = {
    ...draft,
    definition: {
      ...draft.definition,
      requested_permissions: [
        'identity:read',
        'data:read',
        'data:write',
        'files:read-selected',
      ],
    },
  };
  expect(
    parseRegistrationDraft(JSON.stringify(extended)).definition
      .requested_permissions,
  ).toHaveLength(4);
  render(view());
  const file = new File(['fixture'], 'registration.json', {
    type: 'application/json',
  });
  Object.defineProperty(file, 'text', {
    value: async () => JSON.stringify(extended),
  });
  fireEvent.change(screen.getByLabelText(label('file')), {
    target: { files: [file] },
  });
  const selected = await screen.findByLabelText(label('selectedFileRead'));
  expect((selected as HTMLInputElement).checked).toBe(false);
  expect(
    (screen.getByLabelText(label('dataWrite')) as HTMLInputElement).checked,
  ).toBe(false);
  expect(apiFetchJson).not.toHaveBeenCalled();
  expect(() =>
    parseRegistrationDraft(
      JSON.stringify({
        ...extended,
        definition: {
          ...extended.definition,
          requested_permissions: ['files:read-selected', 'files:read-selected'],
        },
      }),
    ),
  ).toThrow();
});
