import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Detail, type GitState } from './api';
import { GitWorkspace, useGitState } from './git';
import { translate } from './i18n';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
vi.mock('./views', () => ({
  Changes: ({ linkId }: { linkId: string }) => <div>diff:{linkId}</div>,
}));
const t = translate('ko-KR');
const task = { id: 'task-a', root: '/project', status: 'idle' } as Detail;
const state: GitState = {
  root: '/project/dev',
  available: true,
  branch: 'dev',
  head: '1234567890',
  detached: false,
  upstream: null,
  ahead: null,
  behind: null,
  staged: 0,
  unstaged: 0,
  untracked: 0,
  changed: 0,
  conflicts: 0,
  checked_at: '2026-10-13T00:00:00Z',
};
const links = [
  { id: 'one', root: '/project/dev', source: 'user', state },
  {
    id: 'two',
    root: '/project/worktrees/fix',
    source: 'agent',
    state: { ...state, branch: null, detached: true, changed: 13 },
  },
];
function View({ selected = task }: { selected?: Detail }) {
  const git = useGitState(selected);
  return (
    <GitWorkspace
      key={selected.id}
      task={selected}
      git={git}
      locale="ko-KR"
      t={t}
      onError={vi.fn()}
    />
  );
}
beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(links);
});

it('groups only linked checkouts and binds each diff to its link identity', async () => {
  render(<View />);
  await screen.findByText('/project/worktrees/fix');
  expect(screen.getByText(/detached HEAD.*12345678/)).toBeTruthy();
  expect(screen.getByText('변경 파일 13')).toBeTruthy();
  expect(screen.getByText('diff:one')).toBeTruthy();
  expect(screen.getByText('diff:two')).toBeTruthy();
  expect(screen.queryByText('/project/prod')).toBeNull();
});

it('links an explicit path and unlinks without a Git mutation', async () => {
  render(<View />);
  await screen.findByText('/project/worktrees/fix');
  fireEvent.click(screen.getByText('작업에 경로 연결'));
  fireEvent.change(screen.getByLabelText('Git 체크아웃 경로'), {
    target: { value: '/project/worktrees/new' },
  });
  fireEvent.click(screen.getByRole('button', { name: '경로 연결' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/tasks/task-a/git-links',
      { root: '/project/worktrees/new' },
      'POST',
    ),
  );
  await waitFor(() =>
    expect(
      screen.getAllByRole('button', { name: '연결 해제' })[0],
    ).toHaveProperty('disabled', false),
  );
  fireEvent.click(screen.getAllByRole('button', { name: '연결 해제' })[1]);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/tasks/task-a/git-links/two',
      undefined,
      'DELETE',
    ),
  );
});

it('ignores a late Git response from a previously selected task', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation((path) =>
    path.includes('task-a')
      ? new Promise((r) => {
          resolve = r;
        })
      : Promise.resolve([]),
  );
  const view = render(<View />);
  view.rerender(<View selected={{ ...task, id: 'task-b' }} />);
  await screen.findByText('이 작업에 연결된 Git 경로가 없습니다.');
  await act(async () => resolve(links));
  expect(screen.queryByText('/project/worktrees/fix')).toBeNull();
});
