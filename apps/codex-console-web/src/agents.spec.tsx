import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { useState } from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Task } from './api';
import { AgentsView, type AgentFilters } from './agents';
import { hasFinished, type Agent } from './agent-state';
import { translate } from './i18n';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
const updated_at = '2026-09-30T15:00:00Z';
beforeEach(() => {
  vi.mocked(api).mockReset().mockResolvedValue([]);
});
function task(
  id: string,
  status: string,
  agents: Agent[] = [],
  extra: Partial<Task> = {},
): Task {
  return {
    id,
    title: id,
    status,
    agents,
    updated_at,
    stage: 'plan',
    thread_id: 'root',
    turn_id: null,
    root: '/repo/dev',
    isolated: false,
    approved_revision: null,
    error_code: null,
    permissions: 'read-only',
    pinned: false,
    pending_count: 0,
    executor: 'session',
    ...extra,
  };
}
function agent(status: string, parent_thread_id: string | null = null): Agent {
  return {
    thread_id: parent_thread_id ? 'child' : 'root',
    parent_thread_id,
    name: parent_thread_id ? 'Reviewer' : 'Codex',
    status,
    flags: [],
    updated_at,
  };
}
const tasks = [
  task('Parallel work', 'idle', [
    agent('completed'),
    { ...agent('active', 'root'), activity: 'Checking the diff' },
  ]),
  task('Question', 'waiting', [agent('active')], { pending_count: 1 }),
  task('Result', 'idle', [agent('completed')]),
  task('Failed run', 'failed', [agent('errored')]),
  task('Unverified child', 'idle', [
    agent('completed'),
    agent('notLoaded', 'root'),
  ]),
  task('Draft', 'idle', [], { thread_id: null }),
  task('Template result', 'idle', [agent('completed')], {
    executor: 'templates',
  }),
];

function Harness({
  openTask = vi.fn(),
  templateId = null,
}: {
  openTask?: (id: string) => void;
  templateId?: string | null;
}) {
  const [filters, setFilters] = useState<AgentFilters>({
    status: 'all',
    source: 'all',
    query: '',
  });
  return (
    <AgentsView
      templateId={templateId}
      clearTemplate={vi.fn()}
      tasks={tasks}
      checkedAt={Date.now()}
      failed={false}
      filters={filters}
      onFilters={setFilters}
      t={translate('en-US')}
      openTask={openTask}
      openTemplates={vi.fn()}
      refresh={vi.fn()}
      onError={vi.fn()}
    />
  );
}

it('filters real parallel activity, attention and terminal outcomes without treating idle children as finished', () => {
  const openTask = vi.fn();
  render(<Harness openTask={openTask} />);
  const statuses = within(screen.getByRole('group', { name: 'Status filter' }));
  fireEvent.click(statuses.getByRole('button', { name: /^Running/ }));
  expect(screen.getAllByRole('article')).toHaveLength(2);
  expect(
    screen
      .getByRole('button', { name: 'Parallel work' })
      .closest('article')
      ?.querySelector('.agent-run-step')?.textContent,
  ).toContain('Checking the diff');
  expect(screen.getByText('Reviewer')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Respond to requests' }));
  expect(openTask).toHaveBeenCalledWith('Question');
  fireEvent.click(statuses.getByRole('button', { name: /^Needs attention/ }));
  expect(screen.getByRole('button', { name: 'Failed run' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Question' })).toBeTruthy();
  fireEvent.click(statuses.getByRole('button', { name: /^Finished/ }));
  expect(screen.getAllByRole('article')).toHaveLength(3);
  expect(screen.getByRole('button', { name: 'Failed run' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Unverified child' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Draft' })).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: 'Task source' }), {
    target: { value: 'templates' },
  });
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Template result' })).toBeTruthy();
});

it('never declares unresolved or still-running descendants finished', () => {
  expect(hasFinished(task('failure', 'failed'))).toBe(true);
  expect(hasFinished(task('interrupted', 'interrupted'))).toBe(true);
  for (const status of [
    'active',
    'idle',
    'notLoaded',
    'systemError',
    'notFound',
  ]) {
    expect(
      hasFinished(
        task('root', 'idle', [agent('completed'), agent(status, 'root')]),
      ),
    ).toBe(false);
  }
  expect(hasFinished(task('root', 'uncertain', [agent('completed')]))).toBe(
    false,
  );
});

it('shows search failures, retries, and finds older runs through the server', async () => {
  const search = vi
    .fn()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce([
      task('Older result', 'idle', [agent('completed')]),
    ]);
  vi.mocked(api).mockImplementation(async (path) =>
    path === '/monitor/services' ? [] : search(),
  );
  render(<Harness />);
  fireEvent.change(screen.getByRole('textbox', { name: 'Search tasks' }), {
    target: { value: 'Older' },
  });
  await screen.findByText('Updates delayed. Showing the last received state.');
  expect(screen.queryByText('No matching tasks')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await screen.findByRole('button', { name: 'Older result' });
  await waitFor(() =>
    expect(
      screen.queryByText('Updates delayed. Showing the last received state.'),
    ).toBeNull(),
  );
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe('/overview?search=Older');
});

it('marks unavailable executors without hiding their last reported tasks', async () => {
  vi.mocked(api).mockResolvedValue([
    { id: 'console-session', status: 'healthy', stale: false },
    { id: 'console-templates', status: 'unavailable', stale: false },
  ]);
  render(<Harness />);
  const notice =
    'An execution service is unavailable. Showing the last reported agent state.';
  await screen.findByText(notice);
  expect(screen.getByRole('button', { name: 'Template result' })).toBeTruthy();
  fireEvent.change(screen.getByRole('combobox', { name: 'Task source' }), {
    target: { value: 'session' },
  });
  expect(screen.queryByText(notice)).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: 'Task source' }), {
    target: { value: 'templates' },
  });
  expect(screen.getByText(notice)).toBeTruthy();
});

it('loads all versions by template ID, combines search, and hides global rows while switching templates', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.startsWith('/templates/'))
      return {
        id: path.split('/').at(-1),
        definition: { name: 'Renamed template' },
        archived: true,
      };
    if (path === '/monitor/services') return [];
    if (path.includes('template_id=first'))
      return [
        task('Old template version', 'idle', [agent('completed')], {
          executor: 'templates',
        }),
      ];
    return [];
  });
  const rendered = render(<Harness templateId="first" />);
  expect(screen.queryByRole('button', { name: 'Parallel work' })).toBeNull();
  await screen.findByRole('button', { name: 'Old template version' });
  expect(screen.getByText('Renamed template')).toBeTruthy();
  expect(screen.getByText('Archived template')).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Task source' })).toBeNull();
  fireEvent.change(screen.getByRole('textbox', { name: 'Search tasks' }), {
    target: { value: 'Old' },
  });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/overview?search=Old&template_id=first',
      undefined,
      'GET',
      expect.any(AbortSignal),
    ),
  );
  rendered.rerender(<Harness templateId="second" />);
  expect(
    screen.queryByRole('button', { name: 'Old template version' }),
  ).toBeNull();
  await screen.findByText('No matching tasks');
  expect(api).toHaveBeenCalledWith(
    '/overview?search=Old&template_id=second',
    undefined,
    'GET',
    expect.any(AbortSignal),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
  await screen.findByText('No runs from this template yet');
  expect(api).toHaveBeenCalledWith(
    '/overview?search=&template_id=second',
    undefined,
    'GET',
    expect.any(AbortSignal),
  );
});

it('keeps history scoped when template metadata fails and retries a failed history request without a search term', async () => {
  const request = vi
    .fn()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce([
      task('Recovered history', 'idle', [agent('completed')], {
        executor: 'templates',
      }),
    ]);
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/monitor/services') return [];
    if (path.startsWith('/templates/')) throw new Error('offline');
    return request();
  });
  render(<Harness templateId="first" />);
  await screen.findByText(
    'Template details are unavailable. The history filter is still applied.',
  );
  const warning = await screen.findByText(
    'Updates delayed. Showing the last received state.',
  );
  expect(screen.queryByRole('button', { name: 'Parallel work' })).toBeNull();
  expect(screen.queryByText('No matching tasks')).toBeNull();
  fireEvent.click(
    within(warning.parentElement!).getByRole('button', { name: 'Retry' }),
  );
  await screen.findByRole('button', { name: 'Recovered history' });
  expect(api).toHaveBeenCalledWith(
    '/overview?search=&template_id=first',
    undefined,
    'GET',
    expect.any(AbortSignal),
  );
});
