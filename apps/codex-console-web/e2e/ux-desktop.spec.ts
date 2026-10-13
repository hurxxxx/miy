import { expect, test } from '@playwright/test';
import type { Detail } from '../src/api';
import { openNewTask, submitNewTask } from './task-submission';

for (const viewport of [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`decisions, result history and keyboard resizing at ${viewport.width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('./?view=studio');
    await page
      .getByLabel('본인 전용 비밀번호')
      .fill('console-tests-only-password');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await openNewTask(page);
    await page
      .getByRole('dialog')
      .getByLabel('작업 이름 (선택)')
      .fill('고객 문의 앱 개선');
    await submitNewTask(page);
    await expect(
      page.getByRole('heading', { name: '고객 문의 앱 개선', exact: true }),
    ).toBeVisible();
    const id = new URL(page.url()).searchParams.get('task')!;
    const initial: Detail = await (
      await page.request.get(`api/tasks/${id}`)
    ).json();
    const projectId = '11111111-1111-4111-8111-111111111111';
    const workspaceId = '22222222-2222-4222-8222-222222222222';
    let detail: Detail = {
      ...initial,
      context: {
        area: 'studio',
        app_id: 'support',
        project_id: projectId,
        workspace_id: workspaceId,
      },
      thread_id: 'root',
      stage: 'implement',
      status: 'waiting',
      pending_count: 2,
      summary: {
        project_title: '고객 지원 도구',
        pending_kinds: ['question', 'approval'],
        latest_result: {
          item_id: 'latest',
          turn_id: 'turn-2',
          excerpt: '담당자별 문의 필터를 추가했습니다.',
        },
      },
      results: [
        {
          item_id: 'latest',
          turn_id: 'turn-2',
          text: '담당자별 문의 필터를 추가했습니다.\n\n키보드 탐색 검사를 통과했습니다.',
          completed_at: '2026-10-12T09:30:00Z',
          commands: [{ id: 'check', command: 'pnpm test', exitCode: 0 }],
          changed_files: ['src/inquiries.tsx'],
          evidence_truncated: false,
        },
        {
          item_id: 'previous',
          turn_id: 'turn-1',
          text: '문의 목록과 상태별 검색을 구현했습니다.',
          completed_at: null,
          commands: [{ id: 'old-check', command: 'pnpm check', exitCode: 1 }],
          changed_files: ['src/list.tsx'],
          evidence_truncated: false,
        },
      ],
      requests: [
        {
          id: 'question',
          method: 'item/tool/requestUserInput',
          payload: {
            questions: [
              {
                id: 'filter',
                header: '필터 선택',
                question: '처음 열었을 때 어떤 문의를 보여줄까요?',
                options: [
                  {
                    label: '내 담당 문의',
                    description: '처리할 업무에 바로 집중합니다.',
                  },
                  {
                    label: '전체 문의',
                    description: '팀 전체 현황을 먼저 확인합니다.',
                  },
                ],
              },
            ],
          },
        },
        {
          id: 'approval',
          method: 'item/commandExecution/requestApproval',
          payload: {
            command: 'pnpm test',
            cwd: '/app/support',
            reason: '필터 동작을 검사합니다.',
          },
        },
      ],
    };
    await page.route(`**/api/tasks/${id}`, (route) =>
      route.fulfill({ json: detail }),
    );
    await page.route(`**/api/tasks/${id}/requests/*`, (route) => {
      const requestId = route.request().url().split('/').at(-1);
      detail = {
        ...detail,
        event_id: detail.event_id + 1,
        requests: detail.requests.filter((r) => r.id !== requestId),
        pending_count: detail.pending_count - 1,
      };
      return route.fulfill({ json: detail });
    });
    await page.route(`**/api/workbench/workspaces/${workspaceId}`, (route) =>
      route.fulfill({
        json: {
          id: workspaceId,
          app_id: 'support',
          project_id: projectId,
          state: 'ready',
          admission_open: true,
          operations: [],
          integration: { state: 'not_requested' },
          cleanup: { state: 'not_requested' },
          preview: {
            state: 'ready',
            portal_url: 'https://support.example.test/',
            runtime_revision: 'a'.repeat(40),
          },
        },
      }),
    );
    await page.reload();
    await expect(page.locator('.console-shell > aside')).toHaveCount(1);
    await expect(page.locator('iframe')).toHaveCount(0);
    await expect(
      page.getByRole('link', { name: /개발 앱 열기/ }),
    ).toHaveAttribute('target', '_blank');
    await expect(
      page.locator('.decision-area .request-panel:visible'),
    ).toHaveCount(1);
    await expect(
      page.getByText('직접 답변하기', { exact: true }),
    ).toBeVisible();
    await expect(page.locator('.composer')).toBeHidden();
    const divider = page.getByRole('separator', {
      name: '대화와 결과 영역 크기 조절',
    });
    await expect(divider).toHaveAttribute('aria-valuenow', '50');
    await divider.focus();
    await page.keyboard.press('ArrowRight');
    await expect(divider).toHaveAttribute('aria-valuenow', '55');
    await page.keyboard.press('Home');
    await expect(divider).toHaveAttribute('aria-valuenow', '30');
    await page.keyboard.press('ArrowRight');
    await page.keyboard.press('ArrowRight');
    await page.getByRole('button', { name: '추가 지시 작성' }).click();
    await page
      .getByLabel('요청 내용 입력')
      .fill('선택한 필터를 기억해 주세요.');
    await page.getByRole('button', { name: '추가 지시 작성' }).click();
    await page.screenshot({
      path: testInfo.outputPath(`decisions-${viewport.width}.png`),
    });
    await page
      .getByLabel('필터 선택 · 직접 답변')
      .fill('내 담당 문의를 기본으로 해 주세요.');
    await page.getByRole('button', { name: '승인 2', exact: true }).click();
    await expect(
      page.locator('.decision-area .request-panel:visible'),
    ).toHaveCount(1);
    await page.getByRole('button', { name: '질문 1', exact: true }).click();
    await expect(page.getByLabel('필터 선택 · 직접 답변')).toHaveValue(
      '내 담당 문의를 기본으로 해 주세요.',
    );
    await page
      .getByRole('button', { name: '답변 보내기', exact: true })
      .click();
    await expect(page.getByRole('region', { name: /작업 알림/ })).toContainText(
      '응답을 전달했습니다.',
    );
    await expect(
      page.getByRole('heading', { name: '응답을 기다리고 있어요' }),
    ).toBeFocused();
    await expect(
      page.getByRole('button', { name: '거절', exact: true }),
    ).toBeVisible();
    await page.getByRole('button', { name: '거절', exact: true }).click();
    await expect(page.locator('.composer')).toBeVisible();
    await expect(page.getByLabel('요청 내용 입력')).toBeFocused();
    await expect(page.getByLabel('요청 내용 입력')).toHaveValue(
      '선택한 필터를 기억해 주세요.',
    );
    const stable = await page.locator('.composer').boundingBox();
    const messages = await page.locator('.messages').boundingBox();
    await expect(
      page
        .getByRole('region', { name: /작업 알림/ })
        .getByText(
          '응답을 전달했습니다. 다음 진행 상황을 확인할 수 있습니다.',
          { exact: true },
        ),
    ).toBeHidden({ timeout: 10000 });
    expect(await page.locator('.composer').boundingBox()).toEqual(stable);
    expect(await page.locator('.messages').boundingBox()).toEqual(messages);
    await page.getByLabel('이전 결과 선택').selectOption('previous');
    await expect(page.locator('.result-document')).toContainText(
      '문의 목록과 상태별 검색을 구현했습니다.',
    );
    await expect(page.locator('.result-evidence').first()).toContainText(
      '실패한 명령: 1',
    );
    await expect(page.locator('.result-version time')).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`previous-result-${viewport.width}.png`),
    });
    await page.getByLabel('이전 결과 선택').selectOption('latest');
    await expect(page.locator('.result-document')).toContainText(
      '담당자별 문의 필터를 추가했습니다.',
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole('button', { name: '프로젝트로 돌아가기', exact: true })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`view=studio&project=${projectId}`),
    );
  });
}

test('closing the new task dialog restores focus to its trigger', async ({
  page,
}) => {
  await page.goto('./?view=sessions');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const trigger = page
    .getByRole('button', { name: '새 작업', exact: true })
    .first();
  await trigger.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});
