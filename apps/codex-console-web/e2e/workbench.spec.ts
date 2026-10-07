import { expect, test } from '@playwright/test';

test('failed refreshes retain observations and drafts while invalidating current status', async ({
  page,
}) => {
  let failing = false;
  const revision = 'a'.repeat(40);
  const checked = new Date().toISOString();
  await page.route('**/api/workbench/runtime', async (route) => {
    await route.fulfill({
      status: failing ? 503 : 200,
      json: failing
        ? { error: 'unavailable' }
        : {
            state: 'ready',
            stale: false,
            checked_at: checked,
            items: [
              {
                app_id: 'planner',
                title: 'Planner',
                enabled: true,
                runtime_ai: true,
                installed_revision: revision,
                release_unit: 'miy-app',
              },
            ],
          },
    });
  });
  await page.route('**/api/workbench/platform', async (route) => {
    if (failing)
      return route.fulfill({ status: 503, json: { error: 'unavailable' } });
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({
      json: {
        ...data,
        gitlab: {
          state: 'ready',
          stale: false,
          checked_at: checked,
          branches: [],
          merge_requests: [],
          pipelines: [
            {
              id: 1,
              name: 'release-check',
              status: 'success',
              revision: data.git.head,
            },
          ],
        },
      },
    });
  });
  await page.route('**/api/workbench/apps/planner/usage', async (route) => {
    if (failing)
      return route.fulfill({ status: 503, json: { error: 'unavailable' } });
    const response = await route.fetch();
    await route.fulfill({
      json: {
        ...(await response.json()),
        runtime_state: 'ready',
        stale: false,
        runtime_checked_at: checked,
      },
    });
  });
  await page.goto('./?view=apps');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: /^플래너 개인 계획/ }).click();
  await expect(page.getByText(/^개발 리비전 CI: success/)).toBeVisible();
  await expect(page.getByText(/^연결됨/)).toHaveCount(2);
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  await page.getByLabel('개발 토큰 예산', { exact: true }).fill('3456');
  failing = true;
  const refresh = page
    .getByRole('main')
    .getByRole('button', { name: '새로고침', exact: true });
  await refresh.click();
  await expect(page.getByText(/^연결할 수 없음/)).toHaveCount(2);
  await expect(page.getByText(/^연결됨/)).toHaveCount(0);
  await expect(page.getByText(/^개발 리비전 CI: success/)).toHaveCount(0);
  await expect(
    page.getByText('현재 상태 확인 불가', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('개발 토큰 예산', { exact: true })).toHaveValue(
    '3456',
  );
  await expect(
    page.getByRole('main').getByText(revision.slice(0, 12), { exact: true }),
  ).toBeVisible();
  failing = false;
  await page
    .getByRole('navigation', { name: 'Workbench 메뉴' })
    .getByRole('button', { name: '플랫폼 관리', exact: true })
    .click();
  await expect(page.getByText(/release-check · success/)).toBeVisible();
  failing = true;
  await refresh.click();
  await expect(page.getByText(/^연결할 수 없음/)).toBeVisible();
  await expect(page.getByText(/release-check · success/)).toHaveCount(0);
  await expect(page.getByText(/release-check/)).toBeVisible();
  failing = false;
  await refresh.click();
  await expect(page.getByText(/release-check · success/)).toBeVisible();
  await expect(page.getByText(/^연결됨/)).toBeVisible();
});

test('budget polling preserves the draft and original version across concurrent tabs', async ({
  page,
  context,
}) => {
  await page.goto('./?view=apps');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: /^플래너 개인 계획/ }).click();
  await page.getByRole('button', { name: '예산 편집', exact: true }).click();
  const draft = page.getByLabel('개발 토큰 예산', { exact: true });
  await draft.fill('2345');

  const other = await context.newPage();
  await other.goto('./?view=apps');
  await other.getByRole('button', { name: /^플래너 개인 계획/ }).click();
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
  await page.getByRole('button', { name: /^플래너 개인 계획/ }).click();
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
    page.getByRole('heading', { name: '플래너', exact: true }),
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

test('owner connects an independent checkout and develops it after catalog reload', async ({
  page,
}) => {
  await page.goto('./?view=studio');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const source = await (await page.request.get('__test__/app-source')).json();
  await page.getByRole('button', { name: '앱 소스 연결', exact: true }).click();
  await page.getByLabel('앱 식별자', { exact: true }).fill('sample-app');
  await page
    .getByLabel('저장소 작업 경로', { exact: true })
    .fill(source.repository_root);
  const form = page
    .locator('form')
    .filter({ has: page.getByLabel('저장소 작업 경로') });
  await form.getByRole('button', { name: '앱 소스 연결', exact: true }).click();
  await expect(page.getByRole('button', { name: /^My app/ })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: /^My app/ }).click();
  await expect(page.getByLabel('저장소 작업 경로')).toHaveValue(
    source.repository_root,
  );
  await page.getByRole('button', { name: '수정 개발', exact: true }).click();
  await expect(page).toHaveURL(/task=/);
  const taskId = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${taskId}`)).json();
  expect(task.root).toBe(source.repository_root);
  expect(task.context.source_binding.app_id).toBe('sample-app');
  expect(task.context.release_unit).toBeNull();
  await expect(page.getByLabel('실행 모드')).toHaveValue('plan');
});

test('new project prepares an app source and recovers its result without enabling unconfigured execution', async ({
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
  await page.getByLabel('프로젝트 이름', { exact: true }).fill('내 메모 준비');
  await page
    .getByLabel('요구사항과 완료 기준')
    .fill('나만 볼 수 있는 업무 메모를 관리한다.');
  const appId = `notes-${Date.now()}`;
  await page.getByLabel('앱 식별자').fill(appId);
  await page
    .getByLabel('검토한 기존 앱과 결정 근거')
    .fill('독립 앱의 개인 데이터 계약으로 메모 기능을 개발한다.');
  await page.getByRole('button', { name: '프로젝트 생성·계획 시작' }).click();
  await expect(page).toHaveURL(/task=/);
  const taskId = new URL(page.url()).searchParams.get('task');
  const task = await (await page.request.get(`api/tasks/${taskId}`)).json();
  const projectId = task.context.project_id;
  expect(task.context.app_execution_boundary).toBe('planning_only');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('./?view=studio');
  let project = page
    .locator('.stack')
    .filter({ has: page.getByText('내 메모 준비', { exact: true }) })
    .first();
  await project
    .getByRole('button', { name: '앱 소스 준비', exact: true })
    .click();
  let form = page.getByRole('form', { name: '앱 소스 준비' });
  await form.getByLabel('시작 템플릿').selectOption('private-notes');
  await form
    .getByLabel('앱 저장소 주소')
    .fill(`https://example.test/team/${appId}.git`);
  expect(
    await form.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  // The actual server prepares a disposable source, but its response is lost.
  // Wait for the injected transport failure, since real Git/source preparation
  // can take longer than a UI assertion timeout under parallel test load.
  const lostResponse = page.waitForEvent('requestfailed', {
    predicate: (request) =>
      request.method() === 'POST' &&
      request.url().endsWith(`/projects/${projectId}/source-setup`),
  });
  await page.route(
    `**/api/workbench/projects/${projectId}/source-setup`,
    async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      const response = await route.fetch();
      expect(response.ok()).toBe(true);
      await route.abort('failed');
    },
  );
  await form.getByLabel('앱 저장소 주소').press('Enter');
  await lostResponse;
  await expect(
    form.getByText(
      '준비 결과를 확인하지 못했습니다. 저장된 요청 상태를 먼저 확인하세요.',
    ),
  ).toBeVisible();
  await form
    .getByRole('button', { name: '준비 상태 확인', exact: true })
    .click();
  await expect(form.getByText('앱 소스가 준비되었습니다')).toBeVisible();
  const status = await (
    await page.request.get(`api/workbench/projects/${projectId}/source-setup`)
  ).json();
  expect(status.setup.state).toBe('ready');
  expect(status.setup.app_id).toBe(appId);
  expect(status.setup.template_id).toBe('private-notes');
  expect(status.setup.source_revision).toMatch(/^[0-9a-f]{40}$/);
  await expect(
    project.getByRole('button', { name: '개발 이어가기', exact: true }),
  ).toBeDisabled();
  await expect(
    project.getByText('이 앱의 격리 실행 환경을 연결하세요.'),
  ).toBeVisible();
  // Reload reads the durable result and does not start a native turn or new source operation.
  await page.reload();
  project = page
    .locator('.stack')
    .filter({ has: page.getByText('내 메모 준비', { exact: true }) })
    .first();
  await project
    .getByRole('button', { name: '앱 소스 준비', exact: true })
    .click();
  form = page.getByRole('form', { name: '앱 소스 준비' });
  await expect(form.getByText('앱 소스가 준비되었습니다')).toBeVisible();
  const reloaded = await (
    await page.request.get(`api/workbench/projects/${projectId}/source-setup`)
  ).json();
  expect(reloaded.setup.operation_id).toBe(status.setup.operation_id);
  expect(reloaded.setup.source_revision).toBe(status.setup.source_revision);
  const downloaded = page.waitForEvent('download');
  await project.getByRole('button', { name: '앱 등록 초안 내려받기' }).click();
  const stream = await (await downloaded).createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  const draft = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  expect(draft.schema_version).toBe(1);
  expect(draft.app_id).toBe(appId);
  expect(draft.source_revision).toBe(status.setup.source_revision);
  expect(draft.definition.runtime_profile).toBe('web-api-postgres-v1');
  expect(draft.definition_digest).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(draft.source_manifest_digest).toMatch(/^sha256:[a-f0-9]{64}$/);
  expect(draft).not.toHaveProperty('source_root');
  expect(draft).not.toHaveProperty('token');
  // The real local endpoint must not turn missing platform configuration into
  // either an unregistered app or a successful registration observation.
  const registration = project.getByRole('region', { name: '플랫폼 등록' });
  const checked = page.waitForResponse((response) =>
    response.url().endsWith(`/projects/${projectId}/registration-status`),
  );
  await registration
    .getByRole('button', { name: '등록 상태 확인', exact: true })
    .click();
  const observed = await (await checked).json();
  expect(observed.state).toBe('unknown');
  expect(observed.platform_state).toBe('unconfigured');
  expect(observed.source_revision).toBe(draft.source_revision);
  await expect(registration.getByRole('status')).toHaveText(
    '등록 상태를 확인할 수 없습니다.',
  );
  await expect(registration.getByRole('link')).toHaveCount(0);

  // Supply only the platform observation for the UI handoff. Source preparation,
  // the preceding unavailable read, and Task storage still use the real server.
  await page.route(
    `**/api/workbench/projects/${projectId}/registration-status`,
    (route) =>
      route.fulfill({
        json: {
          ...observed,
          state: 'matching',
          platform_state: 'ready',
          platform_checked_at: new Date().toISOString(),
          registered_source_revision: draft.source_revision,
          registered_definition_digest: draft.definition_digest,
          definition_matches: true,
          revision_matches: true,
        },
      }),
  );
  await registration
    .getByRole('button', { name: '등록 상태 확인', exact: true })
    .click();
  await expect(registration.getByRole('status')).toHaveText(
    '확인 시점의 등록 정보가 일치합니다.',
  );
  await expect(
    project.getByRole('button', { name: '개발 이어가기', exact: true }),
  ).toBeDisabled();
  await registration.getByRole('link', { name: '앱 설치 환경 보기' }).click();
  await expect(page).toHaveURL(new RegExp(`view=apps&app=${appId}`));
  await expect(
    page.getByRole('region', { name: '앱 설치 환경' }),
  ).toBeVisible();
  const priorTask = await (
    await page.request.get(`api/tasks/${taskId}`)
  ).json();
  expect(priorTask.thread_id).toBeNull();
  expect(priorTask.context.app_execution_boundary).toBe('planning_only');
});
