import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { components } from './api.generated';
import type { Detail } from './api';
import { translate } from './i18n';
import { WorkSummary } from './work-summary';

type Segment = components['schemas']['MilestoneOut'];
const t = translate('ko-KR');
const task = { id: 'test', status: 'running', progress: null } as Detail;
const phase = {
  state: 'in_progress',
  summary: 'pnpm test --filter ui; src/internal.ts',
  evidence_ids: [],
  updated_at: '2026-10-13T01:00:00Z',
  headline: '질문 답변 화면 수정',
  one_line: '대화 중 필요한 선택에 화면에서 답할 수 있도록 수정하고 있습니다.',
} as const;
const segment = {
  id: 'one',
  key: 'one',
  title: 'fix/ui-internal',
  state: 'in_progress',
  created_at: phase.updated_at,
  updated_at: phase.updated_at,
  merge: null,
  evidence: [],
  phases: { implementation: { ...phase, evidence_ids: [] } },
} as Segment;

it('shows plain-language actions and one sentence instead of commands and paths', () => {
  render(
    <WorkSummary task={task} segments={[segment]} hasEarlier={false} t={t} />,
  );
  const timeline = screen.getByRole('list');
  expect(within(timeline).getByText('질문 답변 화면 수정')).toBeTruthy();
  expect(within(timeline).getByText(phase.one_line)).toBeTruthy();
  expect(screen.getByText('지금 진행 중인 작업')).toBeTruthy();
  expect(screen.queryByText(/pnpm|src\/internal|fix\/ui/)).toBeNull();
});

it('retains completed work alongside follow-up and prioritizes a blocker over later success', () => {
  const finished = {
    ...segment,
    id: 'done',
    state: 'completed',
    phases: {
      finish: {
        ...phase,
        state: 'completed',
        headline: '작업별 브랜치 연결',
        one_line: '이 작업에 관련된 변경 사항을 모아 볼 수 있게 했습니다.',
        evidence_ids: [],
      },
    },
  } as Segment;
  const blocked = {
    ...segment,
    state: 'needs_attention',
    phases: {
      implementation: {
        ...phase,
        state: 'needs_attention',
        headline: '답변 저장 방식 확인',
        one_line: '저장 방식에 대한 선택이 필요합니다.',
        evidence_ids: [],
      },
      validation: {
        ...phase,
        state: 'completed',
        updated_at: '2026-10-13T02:00:00Z',
        headline: '화면 확인 완료',
        evidence_ids: [],
      },
    },
  } as Segment;
  render(
    <WorkSummary
      task={task}
      segments={[blocked, finished]}
      hasEarlier={false}
      t={t}
    />,
  );
  expect(screen.getByText('확인이 필요한 작업')).toBeTruthy();
  expect(screen.getAllByText('답변 저장 방식 확인')).toHaveLength(2);
  expect(screen.getByText('작업별 브랜치 연결')).toBeTruthy();
  expect(screen.queryByText('화면 확인 완료')).toBeNull();
});

it('labels an idle historical plan honestly and ignores malformed plan steps', () => {
  render(
    <WorkSummary
      task={{
        ...task,
        status: 'idle',
        progress: {
          steps: [
            { step: '답변 화면 확인', status: 'completed' },
            { step: '선택 버튼 수정', status: 'inProgress' },
            { step: '다음 화면 확인', status: 'pending' },
            { step: 'unknown', status: 'unknown' },
            null,
          ],
        },
      }}
      segments={[]}
      hasEarlier={false}
      t={t}
    />,
  );
  expect(
    screen.getByText(
      '아직 작업 요약이 없어 마지막으로 보고된 작업 계획을 표시합니다.',
    ),
  ).toBeTruthy();
  expect(screen.getByText('마지막 보고: 진행 중')).toBeTruthy();
  expect(screen.queryByText('지금 진행 중인 작업')).toBeNull();
  expect(screen.getByText('예정')).toBeTruthy();
  expect(screen.queryByText('unknown')).toBeNull();
});

it('keeps merge verification authoritative when earlier agent phases report success', () => {
  const merge = {
    ...segment,
    title: 'deadbeef → dev',
    state: 'needs_attention',
    phases: {},
    merge: {
      source_root: '/private/source',
      source_branch: 'feature',
      source_head: 'a'.repeat(40),
      target_root: '/private/dev',
      target_branch: 'dev',
      target_head: 'b'.repeat(40),
      verified: false,
    },
  } as Segment;
  render(
    <WorkSummary
      task={{ ...task, status: 'idle' }}
      segments={[merge]}
      hasEarlier={true}
      t={t}
    />,
  );
  expect(screen.getByRole('list').textContent).toContain(
    '작업 내용을 개발에 반영',
  );
  expect(screen.getByRole('list').textContent).toContain(
    '개발 반영이 끝났는지 확인이 필요합니다.',
  );
  expect(screen.queryByText(/deadbeef|\/private/)).toBeNull();
  expect(
    screen.getByText(
      '최근 작업부터 표시합니다. 아래에서 이전 작업도 불러올 수 있습니다.',
    ),
  ).toBeTruthy();
});
