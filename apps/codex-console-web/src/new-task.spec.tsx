import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Detail } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { NewTaskDialog, TaskEnvironmentStatus } from './new-task';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
type Option = components['schemas']['TaskEnvironmentOption'];
const options: Option[] = [
  { kind: 'general', root: '/miy', available: true, read_only: false },
  { kind: 'development', root: '/miy/dev', available: true, read_only: false },
  {
    kind: 'branch',
    root: '/miy/worktrees',
    available: true,
    base_ref: 'dev',
    read_only: false,
  },
  {
    kind: 'existing_branch',
    root: '/miy/worktrees',
    available: true,
    read_only: false,
  },
  { kind: 'production', root: '/miy/prod', available: true, read_only: true },
];
const task: Detail = {
  id: '00000000-0000-4000-8000-000000000010',
  title: 'A task',
  executor: 'session',
  permissions: 'read-only',
  implementation_permissions: ['ask'],
  pinned: false,
  agents: [],
  pending_count: 0,
  results: [],
  stage: 'plan',
  status: 'idle',
  root: '/miy',
  isolated: false,
  thread_id: null,
  turn_id: null,
  approved_revision: null,
  error_code: null,
  updated_at: '2026-10-13T00:00:00Z',
  revisions: [],
  items: [],
  history_truncated: false,
  requests: [],
  event_id: 0,
  attachments: [],
  attachment_limits: { file_bytes: 1, task_bytes: 1, files: 1, selection: 1 },
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/task-environments') return options;
    if (path === '/task-environments/worktrees')
      return [
        {
          branch: 'feature/report',
          root: '/miy/worktrees/report',
          available: true,
        },
        {
          branch: 'feature/unready',
          root: '/miy/worktrees/unready',
          available: false,
          reason: 'task_environment_not_ready',
        },
      ];
    if (path === '/tasks') return task;
    return { ok: true };
  });
});

it('offers five environments and opens a general task with the request preserved', async () => {
  const created = vi.fn();
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={created}
    />,
  );
  expect(
    await screen.findByRole('radio', { name: /일반 작업/ }),
  ).toHaveProperty('checked', true);
  expect(screen.getAllByRole('radio')).toHaveLength(5);
  fireEvent.change(screen.getByLabelText('무엇을 할까요?'), {
    target: { value: '문서를 검토해 주세요' },
  });
  fireEvent.click(screen.getByRole('button', { name: '작업 열기' }));
  await waitFor(() =>
    expect(created).toHaveBeenCalledWith(task, '문서를 검토해 주세요'),
  );
  expect(api).toHaveBeenCalledWith('/tasks', {
    environment: 'general',
    title: '문서를 검토해 주세요',
  });
});

it('uses the selected development environment without creating a branch', async () => {
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('radio', { name: /개발 환경에서 작업/ }),
  );
  fireEvent.click(screen.getByRole('button', { name: '작업 열기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith('/tasks', {
      environment: 'development',
      title: '새 작업',
    }),
  );
});

it('submits a named branch and explains preparation before work starts', async () => {
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('radio', { name: /새 브랜치에서 작업/ }),
  );
  fireEvent.change(screen.getByLabelText('브랜치 이름 (선택)'), {
    target: { value: 'feature/report' },
  });
  expect(
    screen.getByText(/환경 준비가 끝난 뒤 작업할 수 있습니다/),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '작업 열기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith('/tasks', {
      environment: 'branch',
      branch_name: 'feature/report',
      title: '새 작업',
    }),
  );
});

it('marks production as read-only and disables unconfigured environments', async () => {
  vi.mocked(api).mockResolvedValueOnce(
    options.map((item) =>
      item.kind === 'branch'
        ? { ...item, available: false, reason: 'branch_setup_unconfigured' }
        : item,
    ),
  );
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole('radio', { name: /새 브랜치에서 작업/ }),
  ).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('radio', { name: /운영 환경에서 작업/ }));
  expect(screen.getByText(/운영 경로를 읽기 전용으로 점검/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '작업 열기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith('/tasks', {
      environment: 'production',
      title: '새 작업',
    }),
  );
});

it('retries the existing failed environment', async () => {
  const refresh = vi.fn();
  const failed: Detail = {
    ...task,
    status: 'failed',
    root: '/miy/worktrees/owned',
    context: {
      task_environment: {
        kind: 'branch',
        branch: 'feature/report',
        preparation: {
          state: 'failed',
          step: 'dependencies',
          error_code: 'branch_setup_failed',
        },
      },
    },
  };
  render(
    <TaskEnvironmentStatus
      task={failed}
      t={translate('ko-KR')}
      refresh={refresh}
    />,
  );
  expect(screen.getByRole('alert').textContent).toContain('환경 준비에 실패');
  fireEvent.click(screen.getByRole('button', { name: '환경 준비 다시 시도' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(`/tasks/${task.id}/prepare`, {}),
  );
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
});

it('requires an available existing worktree selection and submits its branch', async () => {
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('radio', { name: /기존 브랜치에서 작업/ }),
  );
  expect(screen.getByRole('button', { name: '작업 열기' })).toHaveProperty(
    'disabled',
    true,
  );
  await screen.findByRole('option', { name: 'feature/report' });
  expect(
    screen.getByRole('option', { name: /feature\/unready/ }),
  ).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('기존 워크트리 브랜치'), {
    target: { value: 'feature/report' },
  });
  expect(screen.getByText('./worktrees/report')).toBeTruthy();
  expect(screen.getByText(/이전 대화를 이어가려면 작업 기록/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '작업 열기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith('/tasks', {
      environment: 'existing_branch',
      branch_name: 'feature/report',
      title: '새 작업',
    }),
  );
});

it('refreshes a removed worktree and prevents submission while retaining the request', async () => {
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('radio', { name: /기존 브랜치에서 작업/ }),
  );
  await screen.findByRole('option', { name: 'feature/report' });
  fireEvent.change(screen.getByLabelText('기존 워크트리 브랜치'), {
    target: { value: 'feature/report' },
  });
  fireEvent.change(screen.getByLabelText('무엇을 할까요?'), {
    target: { value: '이어서 검토' },
  });
  vi.mocked(api).mockResolvedValueOnce([]);
  fireEvent.click(screen.getByRole('button', { name: '브랜치 목록 새로고침' }));
  await screen.findByText(/기존 워크트리 브랜치가 없습니다/);
  expect(screen.getByRole('button', { name: '작업 열기' })).toHaveProperty(
    'disabled',
    true,
  );
  expect(screen.getByLabelText('무엇을 할까요?')).toHaveProperty(
    'value',
    '이어서 검토',
  );
});

it('recovers a failed worktree list without creating a task', async () => {
  render(
    <NewTaskDialog
      open
      onOpenChange={vi.fn()}
      t={translate('ko-KR')}
      created={vi.fn()}
    />,
  );
  await screen.findByRole('radio', { name: /기존 브랜치에서 작업/ });
  vi.mocked(api).mockRejectedValueOnce(new Error('failed'));
  fireEvent.click(screen.getByRole('radio', { name: /기존 브랜치에서 작업/ }));
  await screen.findByRole('alert');
  expect(screen.getByRole('button', { name: '작업 열기' })).toHaveProperty(
    'disabled',
    true,
  );
  fireEvent.click(screen.getByRole('button', { name: '브랜치 목록 새로고침' }));
  await screen.findByRole('option', { name: 'feature/report' });
  expect(vi.mocked(api).mock.calls.some(([path]) => path === '/tasks')).toBe(
    false,
  );
});
