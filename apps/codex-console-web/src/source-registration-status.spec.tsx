import { StrictMode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { SourceRegistrationStatus } from './source-registration-status';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));

const projectId = '7c98f6b4-65f7-4429-841e-05ba40cc3d9f';
const props = {
  projectId,
  appId: 'personal-notes',
  bindingVersion: 2,
  t: translate('en-US'),
};
const observation: components['schemas']['SourceRegistrationStatusOut'] = {
  project_id: projectId,
  app_id: props.appId,
  binding_version: 2,
  state: 'matching',
  source_revision: 'a'.repeat(40),
  definition_digest: `sha256:${'b'.repeat(64)}`,
  platform_state: 'ready',
  platform_checked_at: '2026-10-06T19:20:00Z',
  registered_source_revision: 'a'.repeat(40),
  registered_definition_digest: `sha256:${'b'.repeat(64)}`,
  definition_matches: true,
  revision_matches: true,
};
const unchecked = {
  ...observation,
  state: 'unknown',
  registered_source_revision: null,
  registered_definition_digest: null,
  definition_matches: null,
  revision_matches: null,
};
const check = () =>
  fireEvent.click(
    screen.getByRole('button', { name: 'Check registration status' }),
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(observation);
});
afterEach(() => vi.useRealTimers());

it('checks only on explicit request and links matching source metadata to existing app installations', async () => {
  render(
    <StrictMode>
      <SourceRegistrationStatus {...props} />
    </StrictMode>,
  );
  expect(screen.getByText('No registration check yet.')).toBeTruthy();
  expect(api).not.toHaveBeenCalled();
  check();
  await screen.findByText('Registration matches at last check.');
  expect(api).toHaveBeenCalledExactlyOnceWith(
    `/workbench/projects/${projectId}/registration-status`,
    undefined,
    'GET',
    expect.any(AbortSignal),
  );
  expect(screen.getAllByText('Matches')).toHaveLength(2);
  expect(document.querySelector('time')?.dateTime).toBe(
    observation.platform_checked_at,
  );
  expect(
    screen
      .getByRole('link', { name: 'View app installations' })
      .getAttribute('href'),
  ).toBe('?view=apps&app=personal-notes');
  expect(
    screen.getByText(
      'This compares registration at the reported check time. It does not verify installation readiness or deployment.',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      'Source changes after this check are not included. Check again after editing.',
    ),
  ).toBeTruthy();
});

it.each([
  'unconfigured',
  'unavailable',
  'denied',
  'unsupported',
  'ready',
] as const)(
  'never interprets unknown %s metadata as unregistered',
  async (platformState) => {
    vi.mocked(api).mockResolvedValue({
      ...unchecked,
      platform_state: platformState,
      platform_checked_at: null,
    });
    render(<SourceRegistrationStatus {...props} />);
    check();
    await screen.findByText('Registration status could not be confirmed.');
    expect(
      screen.queryByText('No independent registration found at last check.'),
    ).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
    expect(document.querySelector('time')).toBeNull();
    expect(screen.queryByText('App definition')).toBeNull();
  },
);

it('shows a verified absence as a time-bound observation without asserting installation readiness', async () => {
  vi.mocked(api).mockResolvedValue({ ...unchecked, state: 'unregistered' });
  render(<SourceRegistrationStatus {...props} />);
  check();
  await screen.findByText('No independent registration found at last check.');
  expect(document.querySelector('time')?.dateTime).toBe(
    observation.platform_checked_at,
  );
  expect(screen.queryByRole('link')).toBeNull();
});

it.each([
  [true, false],
  [false, true],
  [false, false],
])(
  'distinguishes definition (%s) and source commit (%s) differences',
  async (definitionMatches, revisionMatches) => {
    vi.mocked(api).mockResolvedValue({
      ...observation,
      state: 'different',
      definition_matches: definitionMatches,
      revision_matches: revisionMatches,
      registered_definition_digest: definitionMatches
        ? observation.definition_digest
        : `sha256:${'c'.repeat(64)}`,
      registered_source_revision: revisionMatches
        ? observation.source_revision
        : 'd'.repeat(40),
    });
    render(<SourceRegistrationStatus {...props} />);
    check();
    await screen.findByText('Registration differs at last check.');
    for (const [label, matches] of [
      ['App definition', definitionMatches],
      ['Source commit', revisionMatches],
    ] as const) {
      const row = screen.getByText(label).parentElement;
      expect(
        row && within(row).getByText(matches ? 'Matches' : 'Differs'),
      ).toBeTruthy();
    }
    expect(
      screen.getByRole('link', { name: 'View app installations' }),
    ).toBeTruthy();
  },
);

it('never routes an ID collision into existing app mutation or installation actions', async () => {
  vi.mocked(api).mockResolvedValue({
    ...unchecked,
    state: 'collision',
    registered_source_revision: 'c'.repeat(40),
  });
  render(<SourceRegistrationStatus {...props} />);
  check();
  await screen.findByText('This app ID is registered to a different source.');
  expect(
    screen.getByText(
      'Review the app ID and source connection. This result does not authorize changing the existing app.',
    ),
  ).toBeTruthy();
  expect(screen.queryByRole('link')).toBeNull();
  expect(screen.getAllByRole('button')).toHaveLength(1);
  expect(screen.queryByText('App definition')).toBeNull();
});

it('deduplicates concurrent clicks and bounds a request even when transport ignores abort', async () => {
  vi.useFakeTimers();
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    async () =>
      (await new Promise<unknown>((resolve) => {
        finish = resolve;
      })) as never,
  );
  render(<SourceRegistrationStatus {...props} />);
  const button = screen.getByRole('button', {
    name: 'Check registration status',
  });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(api).toHaveBeenCalledTimes(1);
  const firstSignal = vi.mocked(api).mock.calls[0][3];
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(firstSignal?.aborted).toBe(true);
  expect(screen.getByRole('alert').textContent).toContain(
    'Registration status could not be confirmed.',
  );
  expect(
    screen
      .getByRole('button', { name: 'Check registration status' })
      .hasAttribute('disabled'),
  ).toBe(false);
  expect(api).toHaveBeenCalledTimes(1);
  check();
  await act(async () => Promise.resolve());
  expect(screen.getByText('Registration matches at last check.')).toBeTruthy();
  await act(async () => finish({ ...unchecked, state: 'unregistered' }));
  expect(
    screen.queryByText('No independent registration found at last check.'),
  ).toBeNull();
  expect(screen.getByText('Registration matches at last check.')).toBeTruthy();
});

it('clears a previous successful comparison on refresh failure without inventing an absence', async () => {
  render(<SourceRegistrationStatus {...props} />);
  check();
  await screen.findByText('Registration matches at last check.');
  vi.mocked(api).mockRejectedValueOnce(new ApiError('app_source_changed'));
  check();
  expect(screen.queryByText('Registration matches at last check.')).toBeNull();
  await screen.findByRole('alert');
  expect(screen.queryByRole('link')).toBeNull();
  expect(document.querySelector('time')).toBeNull();
});

it.each(['projectId', 'appId', 'bindingVersion'] as const)(
  'cancels the previous request and clears its observation when %s changes',
  async (field) => {
    let finish!: (value: unknown) => void;
    vi.mocked(api).mockImplementationOnce(
      async () =>
        (await new Promise<unknown>((resolve) => {
          finish = resolve;
        })) as never,
    );
    const view = render(<SourceRegistrationStatus {...props} />);
    check();
    const signal = vi.mocked(api).mock.calls[0][3];
    const changed = {
      ...props,
      ...(field === 'bindingVersion'
        ? { bindingVersion: 3 }
        : { [field]: `${props[field]}-other` }),
    };
    view.rerender(<SourceRegistrationStatus {...changed} />);
    expect(signal?.aborted).toBe(true);
    expect(screen.getByText('No registration check yet.')).toBeTruthy();
    await act(async () => finish(observation));
    expect(
      screen.queryByText('Registration matches at last check.'),
    ).toBeNull();
    expect(api).toHaveBeenCalledTimes(1);
  },
);

it('aborts and removes the deadline when leaving the project', async () => {
  vi.useFakeTimers();
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    async () =>
      (await new Promise<unknown>((resolve) => {
        finish = resolve;
      })) as never,
  );
  const view = render(<SourceRegistrationStatus {...props} />);
  check();
  const signal = vi.mocked(api).mock.calls[0][3];
  view.unmount();
  expect(signal?.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
  await act(async () => finish(observation));
  expect(screen.queryByText('Registration matches at last check.')).toBeNull();
});

it.each([
  null,
  {},
  { ...observation, project_id: 'another-project' },
  { ...observation, app_id: 'another-app' },
  { ...observation, binding_version: 3 },
  { ...observation, state: 'future-value' },
  { ...observation, platform_state: 'unavailable' },
  { ...observation, platform_checked_at: 'invalid-date' },
  { ...observation, definition_matches: false },
  { ...observation, state: 'different' },
  { ...observation, source_revision: 'bad' },
  { ...observation, registered_definition_digest: null },
  { ...unchecked, definition_matches: true },
  {
    ...unchecked,
    state: 'unregistered',
    registered_source_revision: observation.source_revision,
  },
])('fails closed on malformed or mismatched observations %#', async (value) => {
  vi.mocked(api).mockResolvedValue(value);
  render(<SourceRegistrationStatus {...props} />);
  check();
  const alert = await screen.findByRole('alert');
  expect(alert.textContent).toContain(
    'Registration status could not be confirmed.',
  );
  expect(screen.queryByRole('link')).toBeNull();
  expect(screen.queryByText('Registration matches at last check.')).toBeNull();
});

it('uses the Korean snapshot and readiness labels', async () => {
  render(<SourceRegistrationStatus {...props} t={translate('ko-KR')} />);
  fireEvent.click(screen.getByRole('button', { name: '등록 상태 확인' }));
  await screen.findByText('확인 시점의 등록 정보가 일치합니다.');
  expect(
    screen.getByText(
      '표시된 확인 시점의 등록 정보를 비교합니다. 설치의 실행 준비나 배포 성공을 확인하는 기능은 아닙니다.',
    ),
  ).toBeTruthy();
  expect(screen.getByRole('link', { name: '앱 설치 환경 보기' })).toBeTruthy();
});

it('discards a completed observation after the source binding is replaced', async () => {
  const view = render(<SourceRegistrationStatus {...props} />);
  check();
  await screen.findByText('Registration matches at last check.');
  view.rerender(<SourceRegistrationStatus {...props} bindingVersion={3} />);
  expect(screen.queryByText('Registration matches at last check.')).toBeNull();
  expect(screen.queryByRole('link')).toBeNull();
  expect(screen.getByText('No registration check yet.')).toBeTruthy();
  expect(api).toHaveBeenCalledTimes(1);
});
