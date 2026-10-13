import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, type Detail } from './api';
import { translate } from './i18n';
import { TaskHistory } from './task-history';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
const t = translate('ko-KR');
const task = {
  id: '00000000-0000-4000-8000-000000000001',
  event_id: 1,
  items: [],
} as unknown as Detail;
const row = (id: number, event = 'request.sent') => ({
  id,
  event,
  created_at: '2026-10-13T01:00:00Z',
  details: { status: 'idle' },
});
beforeEach(() => vi.mocked(api).mockReset());

it('keeps loaded earlier activity when new live events arrive without duplicating records', async () => {
  vi.mocked(api).mockResolvedValueOnce({
    items: [row(3), row(2)],
    next_before: 2,
  });
  const view = render(<TaskHistory task={task} t={t} />);
  await screen.findAllByText('응답 전달 완료');
  vi.mocked(api).mockResolvedValueOnce({ items: [row(1)], next_before: null });
  fireEvent.click(screen.getByRole('button', { name: '이전 이력 더 보기' }));
  await waitFor(() =>
    expect(screen.getAllByText('응답 전달 완료')).toHaveLength(3),
  );
  vi.mocked(api).mockResolvedValueOnce({
    items: [row(4), row(3)],
    next_before: 3,
  });
  view.rerender(<TaskHistory task={{ ...task, event_id: 2 }} t={t} />);
  await waitFor(() =>
    expect(screen.getAllByText('응답 전달 완료')).toHaveLength(4),
  );
  expect(
    screen.queryByRole('button', { name: '이전 이력 더 보기' }),
  ).toBeNull();
});

it('does not carry an earlier-page failure into a different category', async () => {
  vi.mocked(api).mockResolvedValueOnce({ items: [row(3)], next_before: 3 });
  render(<TaskHistory task={task} t={t} />);
  await screen.findByText('응답 전달 완료');
  let fail!: (reason: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      }),
  );
  fireEvent.click(screen.getByRole('button', { name: '이전 이력 더 보기' }));
  vi.mocked(api).mockResolvedValueOnce({
    items: [row(2, 'turn.accepted')],
    next_before: null,
  });
  fireEvent.click(screen.getByRole('button', { name: '실행·진행' }));
  await screen.findByText('실행 시작');
  await act(async () => fail(new Error('old request failed')));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.queryByText('응답 전달 완료')).toBeNull();
});

it('recovers history after read failure and does not infer old execution outcomes', async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error('offline'));
  render(<TaskHistory task={task} t={t} />);
  await screen.findByRole('alert');
  vi.mocked(api).mockResolvedValueOnce({
    items: [{ ...row(1, 'turn/completed'), details: null }],
    next_before: null,
  });
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByText('실행 종료');
  expect(screen.queryByText('실행 완료')).toBeNull();
  expect(screen.getByText(/기존 이력은 이벤트와 시각만/)).toBeTruthy();
});

it('ignores a delayed history response after the selected task changes', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const view = render(<TaskHistory task={task} t={t} />);
  vi.mocked(api).mockResolvedValueOnce({
    items: [row(9, 'turn.accepted')],
    next_before: null,
  });
  view.rerender(
    <TaskHistory
      task={{ ...task, id: '00000000-0000-4000-8000-000000000002' }}
      t={t}
    />,
  );
  await screen.findByText('실행 시작');
  await act(async () => resolve({ items: [row(1)], next_before: null }));
  expect(screen.queryByText('응답 전달 완료')).toBeNull();
});
