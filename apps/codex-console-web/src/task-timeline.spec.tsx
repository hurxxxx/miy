import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Detail } from './api';
import { TaskTimeline } from './task-timeline';
import { MergeRequest } from './merge-request';
import { ToolCatalog } from './tool-catalog';
import { translate } from './i18n';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
const t = translate('ko-KR');
const task = {
  id: 'task',
  status: 'idle',
  items: [],
  event_id: 1,
  implementation_permissions: ['ask'],
} as unknown as Detail;
const row = {
  id: 'segment',
  key: 'merge:op',
  title: 'feature → dev',
  state: 'needs_attention',
  phases: {
    validation: {
      state: 'completed',
      summary: '검사 12개 통과',
      evidence_ids: [5],
      updated_at: '2026-10-13T00:00:00Z',
    },
  },
  created_at: '2026-10-13T00:00:00Z',
  updated_at: '2026-10-13T00:00:00Z',
  evidence: [
    {
      id: 5,
      event: 'item/completed',
      created_at: '2026-10-13T00:00:00Z',
      details: {
        item_type: 'commandExecution',
        command: 'pnpm test',
        exit_code: 0,
      },
    },
  ],
  merge: {
    source_root: '/worktree',
    source_branch: 'feature',
    source_head: 'a'.repeat(40),
    target_root: '/dev',
    target_branch: 'dev',
    target_head: 'b'.repeat(40),
    verified: false,
    error_code: 'merge_not_verified',
  },
};
beforeEach(() => vi.mocked(api).mockReset());

it('shows reported validation separately from verified Git completion and preserves evidence', async () => {
  vi.mocked(api).mockResolvedValueOnce({ items: [row], next_before: null });
  render(<TaskTimeline task={task} t={t} />);
  await screen.findByText('검사 12개 통과');
  expect(screen.queryByText(/Git 병합 확인 완료/)).toBeNull();
  expect(screen.getByText('pnpm test')).toBeTruthy();
  vi.mocked(api).mockResolvedValueOnce({
    ...row,
    state: 'completed',
    merge: {
      ...row.merge,
      verified: true,
      source_commit: 'a'.repeat(40),
      integrated_head: 'c'.repeat(40),
    },
  });
  fireEvent.click(screen.getByRole('button', { name: '병합 결과 확인' }));
  await screen.findByText(/Git 병합 확인 완료/);
  expect(api).toHaveBeenLastCalledWith(
    '/tasks/task/timeline/segment/verify',
    {},
  );
  expect(screen.getByText('검사 12개 통과')).toBeTruthy();
});

it('submits the reviewed source and destination snapshot and blocks an active turn', async () => {
  vi.mocked(api).mockResolvedValue(row.merge);
  const onMerge = vi.fn().mockResolvedValue(true);
  const view = render(
    <MergeRequest
      task={task}
      linkId="link"
      refreshToken="1"
      busy={false}
      t={t}
      onMerge={onMerge}
    />,
  );
  const button = await screen.findByRole('button', {
    name: '개발로 병합 요청',
  });
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false));
  fireEvent.click(button);
  expect(onMerge).toHaveBeenCalledWith({
    link_id: 'link',
    expected_head: row.merge.source_head,
    expected_branch: 'feature',
    expected_target_head: row.merge.target_head,
    expected_target_branch: 'dev',
  });
  view.rerender(
    <MergeRequest
      task={{ ...task, status: 'running' }}
      linkId="link"
      refreshToken="1"
      busy={false}
      t={t}
      onMerge={onMerge}
    />,
  );
  expect(button.hasAttribute('disabled')).toBe(true);
});

it('browses tool scope and inputs and filters tools without invoking them', async () => {
  vi.mocked(api).mockResolvedValue([
    {
      name: 'miy_task_timeline',
      scope: 'host',
      description: 'Record phases',
      input_schema: {
        properties: { action: { enum: ['list', 'update', 'verify_merge'] } },
      },
    },
    {
      name: 'miy_task_git',
      scope: 'host',
      description: 'Link paths',
      input_schema: {},
    },
  ]);
  render(<ToolCatalog t={t} />);
  await screen.findByText('miy_task_timeline');
  expect(screen.getAllByText('일반 · 코어 개발 작업')).toHaveLength(2);
  fireEvent.change(screen.getByLabelText('도구 검색'), {
    target: { value: '요약' },
  });
  expect(screen.queryByText('miy_task_git')).toBeNull();
  expect(screen.getByText(/"verify_merge"/)).toBeTruthy();
  expect(api).toHaveBeenCalledTimes(1);
});
