import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { AgentActivity } from './agent-activity';
import { activityGroup } from './agent-state';
import type { Task } from './api';
import type { Agent } from './agent-state';
import { translate } from './i18n';

const agent = (status: string, overrides: Partial<Agent> = {}): Agent => ({
  thread_id: 'root',
  parent_thread_id: null,
  name: 'Codex',
  status,
  flags: [],
  updated_at: '2026-09-30T12:00:00Z',
  ...overrides,
});
const task = (overrides: Partial<Task> = {}): Task => ({
  id: 'task',
  title: 'Repository review',
  status: 'idle',
  stage: 'plan',
  thread_id: null,
  turn_id: null,
  root: '/repo',
  isolated: false,
  approved_revision: null,
  error_code: null,
  updated_at: '2026-09-30T12:00:00Z',
  permissions: 'read-only',
  pinned: false,
  agents: [],
  pending_count: 0,
  executor: 'session',
  ...overrides,
});
const child = (status: string, overrides: Partial<Agent> = {}) =>
  agent(status, {
    thread_id: 'child',
    parent_thread_id: 'root',
    name: 'Reviewer',
    ...overrides,
  });

it('only reports execution and completion supported by native states', () => {
  expect(activityGroup(task())).toBeNull();
  for (const status of ['active', 'running', 'pendingInit']) {
    expect(
      activityGroup(task({ agents: [agent('completed'), child(status)] })),
    ).toBe('running');
  }
  for (const status of ['idle', 'notLoaded']) {
    expect(
      activityGroup(task({ agents: [agent('completed'), child(status)] })),
    ).toBe('waiting');
  }
  for (const status of ['completed', 'interrupted', 'shutdown']) {
    expect(
      activityGroup(
        task({
          agents: [
            agent('completed'),
            child(status, { flags: ['waitingOnApproval'] }),
          ],
        }),
      ),
    ).toBe('finished');
  }
  for (const status of [
    'errored',
    'systemError',
    'notFound',
    'futureUnknownState',
  ]) {
    expect(activityGroup(task({ agents: [child(status)] }))).toBe('attention');
  }
  expect(
    activityGroup(
      task({
        agents: [
          agent('completed'),
          child('active', { flags: ['waitingOnUserInput'] }),
        ],
      }),
    ),
  ).toBe('attention');
});

it('keeps completed work visible, groups parallel children, and opens its original task', async () => {
  const props = {
    t: translate('en-US'),
    checkedAt: Date.now(),
    failed: false,
    openTask: vi.fn(),
    openSessions: vi.fn(),
  };
  const running = task({
    thread_id: 'root',
    status: 'running',
    agents: [
      agent('active'),
      child('active'),
      child('idle', { thread_id: 'idle' }),
    ],
    progress: { steps: [{ step: 'Inspect changes', status: 'inProgress' }] },
  });
  const { rerender } = render(<AgentActivity {...props} tasks={[running]} />);
  fireEvent.click(
    screen.getByRole('button', { name: /Agent activity.*Running agents: 2/ }),
  );
  const dialog = await screen.findByRole('dialog', { name: 'Agent activity' });
  expect(within(dialog).getByText('Inspect changes')).toBeTruthy();
  fireEvent.click(within(dialog).getByText('Agent details'));
  expect(within(dialog).getAllByText('Reviewer')).toHaveLength(2);
  rerender(
    <AgentActivity
      {...props}
      tasks={[
        {
          ...running,
          status: 'idle',
          agents: [
            agent('completed'),
            child('active', { activity: 'Reviewing the final diff' }),
          ],
        },
      ]}
    />,
  );
  expect(dialog.querySelector('.agent-current-step')?.textContent).toBe(
    'Reviewing the final diff',
  );
  expect(
    screen.getByRole('button', { name: /Agent activity.*Running agents: 1/ }),
  ).toBeTruthy();
  rerender(
    <AgentActivity
      {...props}
      tasks={[
        {
          ...running,
          status: 'idle',
          agents: [agent('completed'), child('completed')],
        },
      ]}
    />,
  );
  expect(
    screen.getByRole('button', {
      name: /Agent activity.*Running agents: 0.*Recently finished: 1/,
    }),
  ).toBeTruthy();
  const finished = within(dialog).getByRole('region', {
    name: 'Recently finished',
  });
  fireEvent.click(
    within(finished).getByRole('button', { name: /Repository review/ }),
  );
  expect(props.openTask).toHaveBeenCalledWith('task');
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('marks stale data and limits recent results without hiding attention', async () => {
  const tasks = Array.from({ length: 8 }, (_, index) =>
    task({ id: `${index}`, title: `Finished ${index}`, status: 'review' }),
  );
  tasks.push(
    task({
      id: 'attention',
      title: 'Waiting task',
      status: 'waiting',
      pending_count: 1,
    }),
  );
  const openSessions = vi.fn();
  render(
    <AgentActivity
      tasks={tasks}
      checkedAt={Date.now()}
      failed
      t={translate('en-US')}
      openTask={vi.fn()}
      openSessions={openSessions}
    />,
  );
  fireEvent.click(
    screen.getByRole('button', { name: /Agent activity.*Updates delayed/ }),
  );
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByText(
      'Updates delayed. Showing the last received state.',
    ),
  ).toBeTruthy();
  expect(
    within(dialog).getAllByRole('button', { name: /^Finished/ }),
  ).toHaveLength(5);
  expect(
    within(dialog).getByRole('button', { name: /Waiting task/ }),
  ).toBeTruthy();
  fireEvent.click(within(dialog).getByRole('button', { name: 'All sessions' }));
  expect(openSessions).toHaveBeenCalledOnce();
});
