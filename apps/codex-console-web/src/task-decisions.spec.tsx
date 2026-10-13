import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { type Detail } from './api';
import { translate } from './i18n';
import { TaskDecisions } from './task-decisions';

const t = translate('ko-KR');
const task = {
  id: '00000000-0000-4000-8000-000000000001',
  requests: [
    {
      id: 'question',
      method: 'item/tool/requestUserInput',
      payload: {
        questions: [
          {
            id: 'scope',
            header: '범위',
            question: '어디부터 확인할까요?',
            options: [],
          },
        ],
      },
    },
  ],
} as unknown as Detail;

it('returns focus to the preserved composer after an accepted response and announces its receipt', async () => {
  const answer = vi.fn().mockResolvedValue(true);
  const view = render(
    <section>
      <TaskDecisions task={task} t={t} busy={false} onAnswer={answer} />
      <form className="composer">
        <textarea aria-label="Draft" defaultValue="Keep this instruction" />
      </form>
    </section>,
  );
  fireEvent.change(screen.getByLabelText('범위 · 직접 답변'), {
    target: { value: '계약부터 확인' },
  });
  const submit = screen.getByRole('button', { name: '답변 보내기' });
  submit.focus();
  fireEvent.click(submit);
  await screen.findByText(
    '응답을 전달했습니다. 다음 진행 상황을 확인할 수 있습니다.',
  );
  view.rerender(
    <section>
      <TaskDecisions
        task={{ ...task, requests: [] }}
        t={t}
        busy={false}
        onAnswer={answer}
      />
      <form className="composer">
        <textarea aria-label="Draft" defaultValue="Keep this instruction" />
      </form>
    </section>,
  );
  expect(screen.getByLabelText('Draft')).toHaveProperty(
    'value',
    'Keep this instruction',
  );
  expect(document.activeElement).toBe(screen.getByLabelText('Draft'));
  const notifications = screen.getByRole('region', { name: /작업 알림/ });
  expect(
    within(notifications).getByText(
      '확인된 진행 내역은 작업 이력에서 다시 볼 수 있습니다.',
    ),
  ).toBeTruthy();
});

it('keeps the response draft and suppresses duplicate submissions while delivery is pending', async () => {
  let finish!: (value: boolean) => void;
  const answer = vi.fn(
    () =>
      new Promise<boolean>((resolve) => {
        finish = resolve;
      }),
  );
  render(<TaskDecisions task={task} t={t} busy={false} onAnswer={answer} />);
  const input = screen.getByLabelText('범위 · 직접 답변');
  fireEvent.change(input, { target: { value: '입력 유지' } });
  const submit = screen.getByRole('button', { name: '답변 보내기' });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(answer).toHaveBeenCalledTimes(1);
  await act(async () => finish(false));
  await waitFor(() =>
    expect(
      screen.getByText(
        '응답 전달을 확인하지 못했습니다. 현재 요청 상태를 확인해 주세요.',
      ),
    ).toBeTruthy(),
  );
  expect(input).toHaveProperty('value', '입력 유지');
  expect(
    screen.getByRole('heading', { name: '응답을 기다리고 있어요' }),
  ).toBeTruthy();
});

const asyncTask = {
  ...task,
  requests: [],
  status: 'idle',
  thread_id: 'native-thread',
  async_questions: [
    {
      id: 'async-one',
      item_id: 'native-item',
      turn_id: 'native-turn',
      state: 'pending',
      questions: [
        { title: '예외를 허용할까요?', options: ['허용', '정책 유지'] },
      ],
    },
  ],
} as Detail;

it('shows an async question after completion and sends only an explicit answer', async () => {
  const answer = vi.fn().mockResolvedValue(true);
  render(
    <TaskDecisions
      task={asyncTask}
      t={t}
      busy={false}
      onAnswer={vi.fn()}
      onAsyncAnswer={answer}
    />,
  );
  const submit = screen.getByRole('button', { name: '답변하고 계속' });
  expect(submit).toHaveProperty('disabled', true);
  expect(answer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('radio', { name: '정책 유지' }));
  fireEvent.click(submit);
  fireEvent.click(submit);
  await waitFor(() => expect(answer).toHaveBeenCalledTimes(1));
  expect(answer).toHaveBeenCalledWith('async-one', {
    answers: { '0': ['정책 유지'] },
  });
});

it('separates unanswered recovered questions, uncertain delivery and completed history', () => {
  const row = asyncTask.async_questions[0];
  render(
    <TaskDecisions
      task={{
        ...asyncTask,
        async_questions: [
          { ...row, state: 'unconfirmed' },
          {
            ...row,
            id: 'uncertain',
            state: 'uncertain',
            questions: [{ title: '전달 확인', options: [] }],
          },
          {
            ...row,
            id: 'answered',
            state: 'answered',
            answers: { '0': ['정책 유지'] },
            questions: [{ title: '이전 질문', options: [] }],
          },
        ],
      }}
      t={t}
      busy={false}
      onAnswer={vi.fn()}
      onAsyncAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/과거 응답 여부를 확인할 수 없습니다/)).toBeTruthy();
  expect(screen.getByText(/응답 전달 여부를 확인해야 합니다/)).toBeTruthy();
  const cards = document.querySelectorAll('.async-question');
  expect(cards).toHaveLength(2);
  expect(
    within(cards[1] as HTMLElement).getByRole('button', {
      name: '답변하고 계속',
    }),
  ).toHaveProperty('disabled', true);
  expect(screen.queryByRole('group', { name: '이전 질문' })).toBeNull();
});
