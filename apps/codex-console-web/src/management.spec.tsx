import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api } from './api';
import { translate } from './i18n';
import { AgentTree, ManagementView } from './management';
import type { Agent } from './agent-state';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-06T12:59:55Z'));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('shows observed version and time with unknown stale status without executing operations', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/monitor/services')
      return [
        {
          id: 'app-one',
          name: 'App one',
          environment: 'preview',
          status: 'healthy',
          version: 'build-42',
          checked_at: '2026-10-06T12:34:56Z',
          stale: true,
        },
        {
          id: 'app-two',
          name: 'App two',
          environment: 'preview',
          status: 'unknown',
          version: null,
          checked_at: null,
          stale: false,
        },
      ] as never;
    if (path === '/monitor/host') return {} as never;
    throw new Error('Unexpected request');
  });
  const openTemplates = vi.fn();
  render(
    <ManagementView
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      openTemplates={openTemplates}
    />,
  );
  const one = (await screen.findByText('App one')).closest('article')!;
  expect(within(one).getByText('Observed version: build-42')).toBeTruthy();
  expect(within(one).getByText('Unknown')).toBeTruthy();
  expect(within(one).queryByText('Healthy')).toBeNull();
  expect(within(one).getByText(/Stale observation/).textContent).toContain(
    new Date('2026-10-06T12:34:56Z').toLocaleString(),
  );
  const two = screen.getByText('App two').closest('article')!;
  expect(within(two).getByText('Observed version: Unknown')).toBeTruthy();
  fireEvent.click(
    within(one).getByRole('button', { name: 'Use a task template' }),
  );
  expect(openTemplates).toHaveBeenCalledOnce();
  expect(
    vi
      .mocked(api)
      .mock.calls.every(
        ([, body, method]) => body === undefined && method === 'GET',
      ),
  ).toBe(true);
});

const recordedAgent = (observation: Agent['observation']): Agent => ({
  thread_id: 'native-thread',
  name: 'Reviewer',
  status: 'completed',
  flags: [],
  updated_at: '2026-10-06T13:00:00Z',
  observation,
});
const observed = (
  changes: Partial<NonNullable<Agent['observation']>> = {},
): NonNullable<Agent['observation']> => ({
  thread_status: 'notLoaded',
  thread_checked_at: '2026-10-06T12:59:50Z',
  last_turn: {
    id: 'completed-turn',
    status: 'completed',
    observed_at: '2026-10-06T12:58:00Z',
  },
  attempted_at: '2026-10-06T12:59:50Z',
  error_code: null,
  freshness: 'fresh',
  ...changes,
});

function detailValue(container: HTMLElement, label: string) {
  const result = within(container).getByText(label, {
    selector: 'dt',
  }).nextElementSibling;
  if (!(result instanceof HTMLElement))
    throw new Error('Expected a labeled definition');
  return result;
}

it('keeps a saved completed result alongside a freshly unloaded native thread', () => {
  render(
    <AgentTree agents={[recordedAgent(observed())]} t={translate('en-US')} />,
  );
  const summary = screen.getByText('Reviewer').closest('summary');
  if (!summary) throw new Error('Expected agent summary');
  expect(summary.textContent).toContain('Stored state: Completed');
  expect(summary.textContent).toContain('Native state: Not loaded');
  fireEvent.click(summary);
  const card = summary.parentElement;
  if (!card) throw new Error('Expected agent details');
  expect(detailValue(card, 'Stored state').textContent).toBe('Completed');
  expect(detailValue(card, 'Last observed turn').textContent).toContain(
    'Completed',
  );
  expect(
    detailValue(card, 'Native state checked').querySelector('time')?.dateTime,
  ).toBe('2026-10-06T12:59:50Z');
  expect(
    detailValue(card, 'Record updated').querySelector('time')?.dateTime,
  ).toBe('2026-10-06T13:00:00Z');
  expect(
    detailValue(card, 'Turn observed').querySelector('time')?.dateTime,
  ).toBe('2026-10-06T12:58:00Z');
});

it.each(['stale', 'unavailable'] as const)(
  'marks %s current state unknown without replacing successful observations or stored results',
  (freshness) => {
    const value = recordedAgent(
      observed({
        freshness,
        error_code: freshness === 'unavailable' ? 'read_failed' : null,
        attempted_at: '2026-10-06T13:00:10Z',
        thread_status: 'idle',
      }),
    );
    render(<AgentTree agents={[value]} t={translate('en-US')} />);
    const summary = screen.getByText('Reviewer').closest('summary');
    if (!summary?.parentElement) throw new Error('Expected agent details');
    fireEvent.click(summary);
    expect(summary.textContent).toContain('Stored state: Completed');
    expect(summary.textContent).toContain('Current state unknown');
    const card = summary.parentElement;
    expect(detailValue(card, 'Last observed thread state').textContent).toBe(
      'Idle',
    );
    expect(
      detailValue(card, 'Native state checked').querySelector('time')?.dateTime,
    ).toBe('2026-10-06T12:59:50Z');
    expect(
      detailValue(card, 'Last check attempted').querySelector('time')?.dateTime,
    ).toBe('2026-10-06T13:00:10Z');
    expect(within(card).queryByText('Failed', { exact: true })).toBeNull();
    if (freshness === 'unavailable')
      expect(detailValue(card, 'Observation issue').textContent).toBe(
        'Native state read failed',
      );
  },
);

it('does not fabricate native freshness for old rows and localizes the distinction', () => {
  render(<AgentTree agents={[recordedAgent(null)]} t={translate('ko-KR')} />);
  const summary = screen.getByText('Reviewer').closest('summary');
  if (!summary?.parentElement) throw new Error('Expected agent details');
  expect(summary.textContent).toContain('저장된 상태: 완료');
  expect(summary.textContent).toContain('현재 상태 확인 불가');
  fireEvent.click(summary);
  expect(
    detailValue(summary.parentElement, 'Codex 상태 확인 시각').textContent,
  ).toBe('관측 없음');
  expect(detailValue(summary.parentElement, '마지막 관측 턴').textContent).toBe(
    '관측된 턴 없음',
  );
});

it('shows an active native thread and a prior completed turn independently', () => {
  render(
    <AgentTree
      agents={[
        {
          ...recordedAgent(observed({ thread_status: 'active' })),
          status: 'active',
        },
      ]}
      t={translate('en-US')}
    />,
  );
  const summary = screen.getByText('Reviewer').closest('summary');
  if (!summary?.parentElement) throw new Error('Expected agent details');
  fireEvent.click(summary);
  expect(summary.textContent).toContain('Native state: Running');
  expect(
    detailValue(summary.parentElement, 'Last observed turn').textContent,
  ).toContain('Completed');
  expect(detailValue(summary.parentElement, 'Stored state').textContent).toBe(
    'Running',
  );
});

it('expires a retained fresh observation without another successful list response', () => {
  vi.restoreAllMocks();
  vi.useFakeTimers();
  vi.setSystemTime('2026-10-06T12:59:55Z');
  const value = recordedAgent(observed({ thread_status: 'active' }));
  const { rerender, unmount } = render(
    <AgentTree agents={[value]} t={translate('en-US')} />,
  );
  const summary = screen.getByText('Reviewer').closest('summary');
  if (!summary?.parentElement) throw new Error('Expected agent details');
  expect(summary.textContent).toContain('Native state: Running');
  // A failed overview leaves exactly the same successful projection cached.
  rerender(<AgentTree agents={[value]} t={translate('en-US')} />);
  act(() => vi.advanceTimersByTime(24_999));
  expect(summary.textContent).toContain('Native state: Running');
  act(() => vi.advanceTimersByTime(1));
  expect(summary.textContent).toContain('Current state unknown');
  expect(summary.textContent).toContain('Stored state: Completed');
  expect(
    detailValue(summary.parentElement, 'Last observed thread state')
      .textContent,
  ).toBe('Running');
  expect(screen.getByText('Stale observation')).toBeTruthy();
  expect(vi.getTimerCount()).toBe(0);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it('bounds future server clocks and never renews identical native observations after clock rollback', () => {
  vi.restoreAllMocks();
  vi.useFakeTimers();
  vi.setSystemTime('2026-10-06T10:00:00Z');
  const value = recordedAgent(observed({ thread_status: 'active' }));
  const { rerender, unmount } = render(
    <AgentTree agents={[value]} t={translate('en-US')} />,
  );
  act(() => vi.advanceTimersByTime(10_000));
  vi.setSystemTime('2026-10-05T10:00:00Z');
  rerender(<AgentTree agents={[{ ...value }]} t={translate('en-US')} />);
  act(() => vi.advanceTimersByTime(20_000));
  expect(
    screen.getByText('Reviewer').closest('summary')?.textContent,
  ).toContain('Current state unknown');
  rerender(<AgentTree agents={[{ ...value }]} t={translate('en-US')} />);
  expect(screen.getByText('Stale observation')).toBeTruthy();
  expect(vi.getTimerCount()).toBe(0);
  const refreshed = recordedAgent(
    observed({
      thread_status: 'idle',
      thread_checked_at: new Date().toISOString(),
    }),
  );
  rerender(<AgentTree agents={[refreshed]} t={translate('en-US')} />);
  expect(
    screen.getByText('Reviewer').closest('summary')?.textContent,
  ).toContain('Native state: Idle');
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it.each(['stale', 'unavailable'] as const)(
  'never upgrades backend %s after a recent timestamp or local clock change',
  (freshness) => {
    vi.restoreAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime('2026-10-06T12:59:50Z');
    const value = recordedAgent(
      observed({ freshness, thread_status: 'active' }),
    );
    const { rerender } = render(
      <AgentTree agents={[value]} t={translate('en-US')} />,
    );
    vi.setSystemTime('2026-10-06T12:00:00Z');
    rerender(<AgentTree agents={[value]} t={translate('en-US')} />);
    expect(
      screen.getByText('Reviewer').closest('summary')?.textContent,
    ).toContain('Current state unknown');
    expect(vi.getTimerCount()).toBe(0);
  },
);

it('reschedules an early timer wakeup instead of leaving a fresh observation indefinitely', () => {
  vi.restoreAllMocks();
  vi.useFakeTimers();
  vi.setSystemTime('2026-10-06T12:59:55Z');
  const setTimer = globalThis.setTimeout.bind(globalThis);
  vi.spyOn(window, 'setTimeout').mockImplementationOnce((handler, delay) =>
    setTimer(handler, Math.max(0, (delay ?? 0) - 1)),
  );
  render(
    <AgentTree
      agents={[recordedAgent(observed({ thread_status: 'active' }))]}
      t={translate('en-US')}
    />,
  );
  act(() => vi.advanceTimersByTime(24_999));
  expect(
    screen.getByText('Reviewer').closest('summary')?.textContent,
  ).toContain('Native state: Running');
  expect(vi.getTimerCount()).toBe(1);
  act(() => vi.advanceTimersByTime(1));
  expect(
    screen.getByText('Reviewer').closest('summary')?.textContent,
  ).toContain('Current state unknown');
  expect(vi.getTimerCount()).toBe(0);
});
