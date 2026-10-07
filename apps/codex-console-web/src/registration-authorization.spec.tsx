import { StrictMode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { RegistrationAuthorization } from './registration-authorization';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
const task = {
  id: '8234db11-1931-4572-af3b-0fab1f9f7752',
  status: 'idle',
  context: { purpose: 'registration' },
};
const t = translate('en-US');
const status: components['schemas']['Status'] = {
  task_id: task.id,
  operation_id: 'dbf4d2eb-a252-4212-b510-95a7a87d2ec7',
  enabled: true,
  authorization_origin: 'https://miy.example.test',
  authorization_state: 'required',
  state: 'unsubmitted',
  expires_at: null,
  policy: null,
  receipt: null,
  failure_code: null,
  source_revision: null,
};
const mount = () =>
  render(
    <StrictMode>
      <RegistrationAuthorization key={task.id} task={task} t={t} />
    </StrictMode>,
  );
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(status);
});
afterEach(() => vi.useRealTimers());

it('loads current authorization without mutation and requests explicit owner opt-in', async () => {
  mount();
  await screen.findByText('Registration authorization required.');
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
  fireEvent.change(screen.getByLabelText('Development app origin'), {
    target: { value: 'https://preview.example.test' },
  });
  vi.mocked(api).mockResolvedValueOnce({
    status: {
      ...status,
      authorization_state: 'pending',
      policy: {
        app_id: 'app-one',
        origin: 'https://preview.example.test',
        runtime_profile: 'web-api-v1',
        requested_permissions: [],
      },
    },
    authorization_url:
      'https://miy.example.test/apps/authorize-registration?' +
      new URLSearchParams({
        v: '1',
        request_id: 'f7d6768c-f880-4259-a62b-45b43d42160d',
        operation_id: status.operation_id,
        audience: window.location.origin,
        code_challenge: 'a'.repeat(43),
        app_id: 'app-one',
        development_origin: 'https://preview.example.test',
        runtime_profile: 'web-api-v1',
        requested_permissions: '',
      }).toString(),
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Connect registration authorization' }),
  );
  const link = await screen.findByRole('link', { name: 'Approve in MIY' });
  expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  expect(api).toHaveBeenLastCalledWith(
    `/tasks/${task.id}/registration/authorize`,
    { origin: 'https://preview.example.test' },
    'POST',
    expect.any(AbortSignal),
  );
  expect(api).toHaveBeenCalledTimes(3); // StrictMode reads twice; only one explicit mutation.
});

it('does not submit automatically when prior result is unknown and locks the historical origin', async () => {
  vi.mocked(api).mockResolvedValue({
    ...status,
    authorization_state: 'ready',
    state: 'unknown',
    expires_at: '2099-01-01T00:00:00Z',
    source_revision: 'a'.repeat(40),
    policy: {
      app_id: 'app-one',
      origin: 'https://preview.example.test',
      runtime_profile: 'web-api-v1',
      requested_permissions: [],
    },
  });
  mount();
  await screen.findByText(
    'The registration response is unknown. Inspect this same operation; it will not be submitted automatically.',
  );
  expect(
    (screen.getByLabelText('Development app origin') as HTMLInputElement)
      .disabled,
  ).toBe(true);
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Inspect the same registration operation',
    }),
  );
  expect(api).toHaveBeenLastCalledWith(
    `/tasks/${task.id}/registration/receipt`,
    undefined,
    'POST',
    expect.any(AbortSignal),
  );
});

it('keeps a historical receipt separate from current app readiness', async () => {
  vi.mocked(api).mockResolvedValue({
    ...status,
    state: 'registered',
    receipt: {
      operation_id: status.operation_id,
      app_id: 'app-one',
      installation_id: '938c45f2-510e-42cd-a267-766c403cced9',
      definition_digest: `sha256:${'b'.repeat(64)}`,
      source_revision: 'a'.repeat(40),
      created_at: '2026-10-06T12:00:00Z',
    },
  });
  mount();
  await screen.findByText(
    'Historical registration receipt. The development installation was created inactive; this does not confirm current source, activation or deployment.',
  );
  expect(
    screen
      .getByRole('link', { name: 'View app installations' })
      .getAttribute('href'),
  ).toBe('?view=apps&app=app-one');
  const setup = screen.getByRole('link', {
    name: 'Configure my development preview in MIY',
  });
  expect(setup.getAttribute('href')).toBe(
    'https://miy.example.test/apps/app-one/installed/938c45f2-510e-42cd-a267-766c403cced9/setup',
  );
  expect(setup.getAttribute('rel')).toBe('noopener noreferrer');
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
});

it('requires explicit reconnect for another session and prohibits reconnect during active work', async () => {
  vi.mocked(api).mockResolvedValue({
    ...status,
    authorization_state: 'other_session',
  });
  render(
    <RegistrationAuthorization task={{ ...task, status: 'running' }} t={t} />,
  );
  await screen.findByText(
    'This task belongs to another login session. Reconnect explicitly.',
  );
  expect(
    (
      screen.getByRole('button', {
        name: 'Connect registration authorization',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole('button', {
        name: 'Inspect the same registration operation',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it('bounds a read even when transport ignores abort and rejects its late response', async () => {
  vi.useFakeTimers();
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(<RegistrationAuthorization task={task} t={t} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(screen.getByRole('alert')).toBeTruthy();
  await act(async () => resolve(status));
  expect(screen.queryByText('Registration authorization required.')).toBeNull();
  expect(
    (
      screen.getByRole('button', {
        name: 'Refresh authorization status',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});

it('ignores a previous task response after the parent changes the task key', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = render(
    <RegistrationAuthorization key={task.id} task={task} t={t} />,
  );
  const next = { ...task, id: '0c3d0b7e-5d4e-41c7-a1a6-4f1a4ce2dd03' };
  vi.mocked(api).mockResolvedValue({
    ...status,
    task_id: next.id,
    operation_id: '8875a5d0-ea7b-4d6a-8ca0-542b1c6ef7b4',
  });
  view.rerender(<RegistrationAuthorization key={next.id} task={next} t={t} />);
  await screen.findByText('8875a5d0-ea7b-4d6a-8ca0-542b1c6ef7b4');
  await act(async () => resolve(status));
  expect(screen.queryByText(status.operation_id)).toBeNull();
});

it.each([
  { expires_at: 'not-a-date' },
  { expires_at: '2026-10-07T01:02:03' },
  { operation_id: 'another-operation' },
  { policy: {} },
  { state: 'registered', receipt: null },
])(
  'does not present malformed observation as connected: %j',
  async (change) => {
    vi.mocked(api).mockResolvedValue({ ...status, ...change });
    mount();
    await screen.findByRole('alert');
    expect(
      screen.queryByText('Registration authorization connected.'),
    ).toBeNull();
    expect(screen.queryByText(status.operation_id)).toBeNull();
  },
);

it.each([
  'https://elsewhere.example/apps/authorize-registration',
  'https://miy.example.test/another-path',
  'https://miy.example.test/apps/authorize-registration?token=must-not-navigate',
])('does not display an unverified authorization link: %s', async (url) => {
  mount();
  await screen.findByText('Registration authorization required.');
  fireEvent.change(screen.getByLabelText('Development app origin'), {
    target: { value: 'https://preview.example.test' },
  });
  vi.mocked(api).mockResolvedValueOnce({
    status: {
      ...status,
      authorization_state: 'pending',
      policy: {
        app_id: 'app-one',
        origin: 'https://preview.example.test',
        runtime_profile: 'web-api-v1',
        requested_permissions: [],
      },
    },
    authorization_url: url,
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Connect registration authorization' }),
  );
  await screen.findByRole('alert');
  expect(screen.queryByRole('link', { name: 'Approve in MIY' })).toBeNull();
});
