import { expect, test } from '@playwright/test';

test('budget polling preserves the draft and original version across concurrent tabs', async ({
  page,
  context,
}) => {
  await page.goto('./?view=apps');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: /^Planner 개인 계획/ }).click();
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  const draft = page.getByLabel('개발 토큰 예산', { exact: true });
  await draft.fill('2345');

  const other = await context.newPage();
  await other.goto('./?view=apps');
  await other.getByRole('button', { name: /^Planner 개인 계획/ }).click();
  await other.getByRole('button', { name: '예산 편집', exact: true }).click();
  await other.getByLabel('개발 토큰 예산', { exact: true }).fill('6789');
  await other.getByRole('button', { name: '저장', exact: true }).click();
  await expect(
    other.getByText('토큰 예산: 6,789', { exact: true }),
  ).toBeVisible();

  await page
    .getByRole('main')
    .getByRole('button', { name: '새로고침', exact: true })
    .click();
  await expect(
    page.getByText('토큰 예산: 6,789', { exact: true }),
  ).toBeVisible();
  await expect(draft).toHaveValue('2345');
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/workbench/apps/planner/budget') &&
      response.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: '저장', exact: true }).click();
  expect((await saved).status()).toBe(409);
  await expect(draft).toHaveValue('2345');
  const current = await (
    await page.request.get('api/workbench/apps/planner/usage')
  ).json();
  expect(current.budget.development_tokens).toBe(6789);
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  await expect(draft).toHaveValue('6789');
  await other.close();
});

test('Workbench connects app maintenance to Studio without granting deployment authority', async ({
  page,
}) => {
  await page.goto('./');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'MIY Studio' })).toBeVisible();
  await expect(page).toHaveTitle('MIY Workbench');
  const navigation = page.getByRole('navigation', { name: 'Workbench 메뉴' });
  await navigation
    .getByRole('button', { name: '앱 관리 센터', exact: true })
    .click();
  await page.getByRole('button', { name: /^Planner 개인 계획/ }).click();
  await expect(page.getByText('금액 미제공', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '문제 등록', exact: true }).click();
  const title = `일정 패치 ${Date.now()}`;
  await page.getByLabel('문제·패치 제목').fill(title);
  await page
    .getByLabel('내용·처리 계획')
    .fill('일정 정렬 오류를 확인하고 회귀 검사를 추가한다.');
  await page.getByLabel('목표 일정').fill('2025-01-01');
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  await page.getByLabel('개발 토큰 예산', { exact: true }).fill('1000');
  const refreshed = page.waitForResponse((response) =>
    response.url().endsWith('/api/workbench/catalog'),
  );
  await page
    .getByRole('main')
    .getByRole('button', { name: '새로고침', exact: true })
    .click();
  await refreshed;
  await expect(page.getByLabel('개발 토큰 예산', { exact: true })).toHaveValue(
    '1000',
  );
  await page.getByRole('button', { name: '저장', exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Planner', exact: true }),
  ).toBeVisible();
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  await expect(
    page.getByText('토큰 예산: 1,000', { exact: true }),
  ).toBeVisible();
  const patch = page.locator('.wb-patch').filter({ hasText: title });
  await patch.getByRole('button', { name: '패치 준비', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: title, exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('실행 모드')).toHaveValue('plan');
  const id = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${id}`)).json();
  expect(task.context.app_id).toBe('planner');
  expect(task.context.maintenance_id).toBeTruthy();
  expect(task.thread_id).toBeNull();
  expect(task.permissions).toBe('read-only');
  await expect(page.getByLabel('요청 내용 입력')).toContainText(
    'Investigate this maintenance item',
  );
  await navigation
    .getByRole('button', { name: '플랫폼 관리', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: '로컬 소스' })).toBeVisible();
  await expect(page.getByText(/^연동 미설정/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test('new app project records reuse rationale and opens a plan with its own context', async ({
  page,
}) => {
  await page.goto('./?view=studio');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page
    .getByRole('button', { name: '새 앱 프로젝트', exact: true })
    .click();
  await page.getByLabel('프로젝트 이름', { exact: true }).fill('검토 워크플로');
  await page
    .getByLabel('요구사항과 완료 기준')
    .fill('요청을 검토하고 승인 기록을 관리한다.');
  const appId = `review-${Date.now()}`;
  await page.getByLabel('앱 식별자').fill(appId);
  await page
    .getByLabel('검토한 기존 앱과 결정 근거')
    .fill('PMS 검토 완료. 독립된 승인 기록과 상태 전이가 필요하다.');
  await page.getByRole('button', { name: '프로젝트 생성·계획 시작' }).click();
  await expect(
    page.getByRole('heading', { name: '검토 워크플로', exact: true }),
  ).toBeVisible();
  const id = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${id}`)).json();
  expect(task.context.app_id).toBe(appId);
  expect(task.context.project_id).toBeTruthy();
  expect(task.context.reuse_decision).toBe('new');
  expect(task.thread_id).toBeNull();
});
