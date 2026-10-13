import { expect, test } from '@playwright/test';

test('restores a missed question and displays only the linked detached worktree with its diff', async ({
  page,
}) => {
  await page.goto('./');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.locator('#console-sidebar')).toBeAttached();
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === 'codex_console_csrf',
  )!.value;
  const headers = { origin: new URL(page.url()).origin, 'x-csrf-token': csrf };
  const created = await page.request.post('api/tasks', {
    headers,
    data: { title: '질문과 워크트리 검증' },
  });
  expect(created.ok()).toBe(true);
  const task = await created.json();
  await page.request.post(`api/tasks/${task.id}/messages`, {
    headers,
    data: { operation_id: crypto.randomUUID(), text: 'Inspect the fixture' },
  });
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`api/tasks/${task.id}`)).json()).status,
    )
    .toBe('idle');
  const fixture = await page.request.post('__test__/questions-git', {
    headers,
    data: { task_id: task.id },
  });
  expect(fixture.ok()).toBe(true);
  const paths = await fixture.json();
  await page.goto(`./?task=${task.id}`);
  await expect(
    page.getByRole('heading', { name: '질문과 워크트리 검증', exact: true }),
  ).toBeVisible();
  await page.getByText('질문 이력', { exact: true }).click();
  await page.getByRole('button', { name: '대화에서 질문 복원' }).click();
  await expect(
    page.getByRole('radio', { name: '정책 유지', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/과거 응답 여부를 확인할 수 없습니다/),
  ).toBeVisible();
  await expect(page.getByLabel('요청 내용 입력')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 667 });
  await expect(page.getByLabel('요청 내용 입력')).toBeInViewport();
  const submit = page.getByRole('button', { name: '답변하고 계속' });
  await submit.scrollIntoViewIfNeeded();
  await expect(submit).toBeInViewport();
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole('button', { name: '변경사항', exact: true }).click();
  await page
    .getByRole('button', { name: '브랜치·워크트리 연결', exact: true })
    .click();
  await page.getByLabel('Git 체크아웃 경로').fill(paths.root);
  await page.getByRole('button', { name: '경로 연결', exact: true }).click();
  await expect(
    page.locator('.git-checkout').filter({ hasText: paths.root }),
  ).toContainText('변경 파일 13');
  await expect(
    page.locator('.git-checkout').filter({ hasText: paths.root }),
  ).toContainText('detached HEAD');
  await expect(page.getByText(paths.unrelated, { exact: true })).toHaveCount(0);
  const checkout = page
    .locator('.git-checkout')
    .filter({ hasText: paths.root });
  await checkout.getByRole('button', { name: /README.md/ }).click();
  await expect(checkout.locator('.diff-content')).toBeAttached();
  await checkout.getByRole('button', { name: /detached HEAD/ }).click();
  await checkout
    .getByRole('button', { name: `연결 해제: ${paths.root}`, exact: true })
    .click();
  await expect(checkout).toHaveCount(0);
  await page
    .getByRole('button', { name: '브랜치·워크트리 연결', exact: true })
    .click();
  await page.getByLabel('Git 체크아웃 경로').fill(paths.root);
  await page.getByRole('button', { name: '경로 연결', exact: true }).click();
  await expect(checkout).toContainText('변경 파일 13');
  await page.reload();
  await expect(
    page.getByRole('radio', { name: '정책 유지', exact: true }),
  ).toBeVisible();
  await page.getByRole('radio', { name: '정책 유지', exact: true }).click();
  await page.getByRole('button', { name: '답변하고 계속' }).click();
  await expect(
    page.getByRole('radio', { name: '정책 유지', exact: true }),
  ).toHaveCount(0);
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`api/tasks/${task.id}`)).json())
          .async_questions[0].state,
    )
    .toBe('answered');
});
