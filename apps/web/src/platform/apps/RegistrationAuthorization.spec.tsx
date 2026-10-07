import { act, fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { Link, MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import { apiFetchJson, ApiRequestError } from '@/src/platform/api/client';
import RegistrationAuthorization from './RegistrationAuthorization';
import {
  parseRegistrationAuthorizationQuery,
  parseRegistrationAuthorizationResponse,
  REGISTRATION_AUTHORIZATION_API,
} from './registration-authorization';

vi.mock('@/src/platform/api/client', async (original) => ({
  ...(await original<typeof import('@/src/platform/api/client')>()),
  apiFetchJson: vi.fn(),
}));
const actor = 'c0000000-0000-4000-8000-000000000001';
const auth = vi.hoisted(() => ({
  token: 'synthetic-owner-token',
  user: {
    id: 'c0000000-0000-4000-8000-000000000001',
    email: 'owner@example.test',
  },
}));
vi.mock('@/src/platform/auth/auth-provider', () => ({ useAuth: () => auth }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const label = (key: string) => `independentApps.authorization.${key}`;
const query = new URLSearchParams({
  v: '1',
  request_id: 'a0000000-0000-4000-8000-000000000001',
  operation_id: 'b0000000-0000-4000-8000-000000000001',
  audience: 'http://127.0.0.1:38102/workbench',
  code_challenge: 'c'.repeat(43),
  app_id: 'personal-notes',
  development_origin: 'https://notes.example.test',
  runtime_profile: 'web-api-postgres-v1',
  requested_permissions: 'identity:read,data:read',
});
const input = parseRegistrationAuthorizationQuery(query.toString());
const response = () => ({
  ...input,
  id: 'd0000000-0000-4000-8000-000000000001',
  actor_user_id: actor,
  callback_url: `${input.audience}/api/registration-authorizations/callback`,
  code: `miyrc_${'s'.repeat(43)}`,
  code_expires_at: new Date(Date.now() + 120_000).toISOString(),
  expires_at: new Date(Date.now() + 300_000).toISOString(),
});
const route = (search = query.toString()) =>
  `/apps/authorize-registration?${search}`;
const view = (search = query.toString()) => (
  <StrictMode>
    <MemoryRouter initialEntries={[route(search)]}>
      <RegistrationAuthorization />
      <Link to={route(search + '&extra=1')}>Change request</Link>
    </MemoryRouter>
  </StrictMode>
);
let submissions: HTMLFormElement[];
beforeEach(() => {
  vi.mocked(apiFetchJson).mockReset();
  auth.token = 'synthetic-owner-token';
  auth.user = { id: actor, email: 'owner@example.test' };
  submissions = [];
  vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(function (
    this: HTMLFormElement,
  ) {
    submissions.push(this);
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const approve = () =>
  fireEvent.click(screen.getByRole('button', { name: label('approve') }));

it('requires explicit consent and posts only the code and nonce in an isolated form body', async () => {
  const value = response();
  vi.mocked(apiFetchJson).mockResolvedValue(value);
  const parentPolicy = document.createElement('meta');
  parentPolicy.name = 'referrer';
  parentPolicy.content = 'no-referrer';
  document.head.append(parentPolicy);
  const app = render(view());
  try {
    expect(apiFetchJson).not.toHaveBeenCalled();
    expect(screen.getByText(auth.user.email)).toBeTruthy();
    expect(screen.getByText(label('limits'))).toBeTruthy();
    approve();
    approve();
    await screen.findByText(label('returning'));
    expect(apiFetchJson).toHaveBeenCalledTimes(1);
    const [path, token, init] = vi.mocked(apiFetchJson).mock.calls[0];
    expect(path).toBe(REGISTRATION_AUTHORIZATION_API);
    expect(token).toBe(auth.token);
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual(input);
    expect(submissions).toHaveLength(1);
    const form = submissions[0];
    expect(form.action).toBe(value.callback_url);
    expect(form.target).toBe('_top');
    expect(form.method).toBe('post');
    expect(Object.fromEntries(new FormData(form))).toEqual({
      request_id: input.request_id,
      code: value.code,
    });
    const frame = document.querySelector('iframe');
    if (!frame) throw new Error('Expected callback form document');
    expect(frame.getAttribute('sandbox')).toBe(
      'allow-forms allow-top-navigation allow-same-origin',
    );
    expect(frame.getAttribute('src')).toBeNull();
    expect(frame.getAttribute('srcdoc')).toBeNull();
    expect(frame.contentDocument?.querySelector('script')).toBeNull();
    expect(
      frame.contentDocument?.querySelector('meta')?.getAttribute('content'),
    ).toBe('origin');
    expect(parentPolicy.content).toBe('no-referrer');
    app.unmount();
    expect(document.querySelector('iframe')).toBeNull();
  } finally {
    parentPolicy.remove();
  }
});

it.each([
  ['extra field', (q: URLSearchParams) => q.append('extra', 'value')],
  ['duplicate field', (q: URLSearchParams) => q.append('app_id', 'other')],
  ['version', (q: URLSearchParams) => q.set('v', '2')],
  ['nonce', (q: URLSearchParams) => q.set('request_id', 'invalid')],
  ['challenge', (q: URLSearchParams) => q.set('code_challenge', 'short')],
  ['app ID', (q: URLSearchParams) => q.set('app_id', 'UPPER')],
  ['HTTP LAN', (q: URLSearchParams) => q.set('audience', 'http://192.0.2.1')],
  [
    'credentials',
    (q: URLSearchParams) => q.set('audience', 'https://user@wb.test'),
  ],
  [
    'callback query',
    (q: URLSearchParams) => q.set('audience', 'https://wb.test?q=1'),
  ],
  [
    'origin path',
    (q: URLSearchParams) =>
      q.set('development_origin', 'https://app.test/path'),
  ],
  ['profile', (q: URLSearchParams) => q.set('runtime_profile', 'worker-v1')],
  [
    'profile permission',
    (q: URLSearchParams) => q.set('runtime_profile', 'web-api-v1'),
  ],
  [
    'permission',
    (q: URLSearchParams) => q.set('requested_permissions', 'admin:write'),
  ],
  [
    'duplicate permission',
    (q: URLSearchParams) =>
      q.set('requested_permissions', 'data:read,data:read'),
  ],
] as const)(
  'rejects an invalid proposal (%s) without sending a request',
  (_name, modify) => {
    const invalid = new URLSearchParams(query);
    modify(invalid);
    render(view(invalid.toString()));
    expect(screen.getByRole('alert').textContent).toBe(label('invalid'));
    expect(screen.queryByRole('button')).toBeNull();
    expect(apiFetchJson).not.toHaveBeenCalled();
  },
);

it.each([
  ['version', { schema_version: 2 }],
  ['authorization ID', { id: 'invalid' }],
  ['nonce', { request_id: 'a0000000-0000-4000-8000-000000000002' }],
  ['operation', { operation_id: 'b0000000-0000-4000-8000-000000000002' }],
  ['owner', { actor_user_id: 'c0000000-0000-4000-8000-000000000002' }],
  ['audience', { audience: 'https://other.example.test' }],
  ['callback', { callback_url: 'https://other.example.test/steal' }],
  ['policy', { policy: { ...input.policy, requested_permissions: [] } }],
  ['token domain', { code: `miyrg_${'s'.repeat(43)}` }],
  ['expired code', { code_expires_at: '2000-01-01T00:00:00Z' }],
  ['missing timezone', { code_expires_at: '2099-01-01T00:00:00' }],
  ['expired grant', { expires_at: '2000-01-01T00:00:00Z' }],
])(
  'rejects a mismatched response (%s) before sending a code anywhere',
  async (_name, change) => {
    vi.mocked(apiFetchJson).mockResolvedValue({ ...response(), ...change });
    render(view());
    approve();
    await screen.findByText(label('unknown'));
    expect(submissions).toHaveLength(0);
    expect(document.querySelector('iframe')).toBeNull();
    expect(apiFetchJson).toHaveBeenCalledTimes(1);
  },
);

it.each(['account', 'token', 'request', 'unmount'])(
  'ignores a late approval after %s changes',
  async (change) => {
    let complete!: (value: unknown) => void;
    vi.mocked(apiFetchJson).mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    );
    const app = render(view());
    approve();
    if (change === 'account') auth.user = { ...auth.user, id: 'other-owner' };
    if (change === 'token') auth.token = 'other-token';
    if (change === 'account' || change === 'token') app.rerender(view());
    if (change === 'request')
      fireEvent.click(screen.getByText('Change request'));
    if (change === 'unmount') app.unmount();
    await act(async () => {
      complete(response());
    });
    expect(submissions).toHaveLength(0);
    expect(vi.mocked(apiFetchJson).mock.calls[0][2]?.signal?.aborted).toBe(
      true,
    );
  },
);

it('bounds an ignored transport timeout, never retries, and discards its late code', async () => {
  const deadline = new AbortController();
  vi.spyOn(AbortSignal, 'timeout').mockReturnValue(deadline.signal);
  let complete!: (value: unknown) => void;
  vi.mocked(apiFetchJson).mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  render(view());
  approve();
  await act(async () => {
    deadline.abort(new DOMException('Timed out', 'TimeoutError'));
  });
  expect(AbortSignal.timeout).toHaveBeenCalledWith(30_000);
  await screen.findByText(label('unknown'));
  approve();
  await act(async () => {
    complete(response());
  });
  expect(submissions).toHaveLength(0);
  expect(apiFetchJson).toHaveBeenCalledTimes(1);
});

it('removes the code and offers recovery when callback navigation never completes', async () => {
  vi.useFakeTimers();
  vi.mocked(apiFetchJson).mockResolvedValue(response());
  render(view());
  await act(async () => {
    approve();
  });
  expect(document.querySelector('iframe')).not.toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });
  expect(screen.getByText(label('unknown'))).toBeTruthy();
  expect(document.querySelector('iframe')).toBeNull();
  approve();
  expect(apiFetchJson).toHaveBeenCalledTimes(1);
});

it.each([
  [404, 'unsupported'],
  [403, 'rejected'],
  [409, 'rejected'],
  [503, 'unknown'],
] as const)(
  'shows a safe fallback on HTTP %s without resubmitting',
  async (status, state) => {
    vi.mocked(apiFetchJson).mockRejectedValue(
      new ApiRequestError(status, 'sensitive-error-marker'),
    );
    render(view());
    approve();
    await screen.findByText(label(state));
    expect(screen.queryByText('sensitive-error-marker')).toBeNull();
    expect(
      screen.getByRole('link', { name: label('manual') }).getAttribute('href'),
    ).toBe('/apps/register');
    approve();
    expect(apiFetchJson).toHaveBeenCalledTimes(1);
    expect(submissions).toHaveLength(0);
  },
);

it('validates bounded queries and exact policy while allowing an empty permission set', () => {
  expect(() => parseRegistrationAuthorizationQuery('x'.repeat(4097))).toThrow();
  const publicApp = new URLSearchParams(query);
  publicApp.set('requested_permissions', '');
  publicApp.set('runtime_profile', 'web-api-v1');
  expect(
    parseRegistrationAuthorizationQuery(publicApp.toString()).policy
      .requested_permissions,
  ).toEqual([]);
  expect(
    parseRegistrationAuthorizationResponse(response(), input, actor).request_id,
  ).toBe(input.request_id);
});

it('describes selected-file permission separately from data writes for the basic profile', () => {
  const proposal = new URLSearchParams(query);
  proposal.set('runtime_profile', 'web-api-v1');
  proposal.set('requested_permissions', 'identity:read,files:read-selected');
  expect(
    parseRegistrationAuthorizationQuery(proposal.toString()).policy
      .requested_permissions,
  ).toEqual(['files:read-selected', 'identity:read']);
  render(view(proposal.toString()));
  expect(
    screen.getByText(
      'independentApps.registration.selectedFileRead, independentApps.registration.profileRead',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(/independentApps\.registration\.dataWrite/),
  ).toBeNull();
  expect(apiFetchJson).not.toHaveBeenCalled();
});
