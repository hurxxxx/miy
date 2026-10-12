import { expect, test, type Page } from '@playwright/test';

const revision = 'a'.repeat(40);
const checkedAt = '2026-10-12T00:00:00Z';
const projects = [
  {
    id: '11111111-1111-4111-8111-111111111111',
    app_id: 'calendar-helper',
    title: '팀 일정 관리',
    summary: '팀의 일정을 검색하고 담당자별로 확인하는 화면을 개선합니다.',
    reuse_decision: 'extend',
    reuse_notes: '기존 일정 앱을 확장합니다.',
    created_at: checkedAt,
  },
  {
    id: '22222222-2222-4222-8222-222222222222',
    app_id: 'candidate-review',
    title: '지원서 검토',
    summary: '지원서를 검토하고 평가 결과를 한곳에서 관리합니다.',
    reuse_decision: 'new',
    reuse_notes: '별도 앱으로 개발합니다.',
    created_at: checkedAt,
  },
];
const apps = Array.from({ length: 28 }, (_, index) => ({
  app_id:
    index === 0
      ? 'calendar-helper'
      : index === 1
        ? 'candidate-review'
        : `sample-app-${index}`,
  title:
    index === 0
      ? '일정 도우미'
      : index === 1
        ? '지원서 검토'
        : `업무 앱 ${index + 1}`,
  summary:
    index === 0
      ? '팀 일정과 담당자별 작업을 한곳에서 확인합니다.'
      : '팀의 업무를 관리하는 앱입니다.',
  icon_key: index === 0 ? 'calendar' : 'layout-grid',
  capabilities: ['업무 관리'],
  source_paths: ['apps/example'],
  source_version: 1,
  release_unit: 'miy-app',
  route_base: '/apps/example',
  preview_url: 'https://preview.example.test/apps/example',
  source_status: 'ready',
  preview_status: 'configured',
  deployment_status: 'configured',
  execution_status: 'configured',
  discovery: 'checkout',
  limitations: [],
}));
function workspace(project: (typeof projects)[number]) {
  return {
    id: `33333333-3333-4333-8333-${project.id.slice(-12)}`,
    project_id: project.id,
    app_id: project.app_id,
    title: `${project.title} 개선`,
    profile: 'app',
    state: 'ready',
    version: 1,
    admission_open: true,
    auto_refresh: true,
    branch: 'feature/example-ui',
    base_revision: revision,
    source_revision: revision,
    preview: {
      state: 'ready',
      portal_url: 'https://preview.example.test/apps/example',
      installation_id: 'preview-example',
      source_revision: revision,
      runtime_revision: revision,
      failure_code: null,
    },
    integration: {
      state: 'not_requested',
      mr_url: null,
      mr_id: null,
      source_revision: null,
      merged_revision: null,
      dev_runtime_revision: null,
      failure_code: null,
    },
    cleanup: { state: 'not_requested', failure_code: null },
    failure_code: null,
    operations: [],
    created_at: checkedAt,
    updated_at: checkedAt,
  };
}
async function browse(
  page: Page,
  route: string,
  environments = projects.map(workspace),
) {
  const mutations: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/workbench/') && request.method() !== 'GET')
      mutations.push(request.method());
  });
  await page.route('**/api/workbench/**', async (request) => {
    const path = new URL(request.request().url()).pathname.split('/api')[1];
    let body: unknown;
    if (path === '/workbench/catalog')
      body = {
        workspaces_available: true,
        registration_authorization_available: false,
        items: apps,
        projects,
        source_revision: revision,
        source_dirty: false,
        checked_at: checkedAt,
      };
    else if (path === '/workbench/runtime')
      body = {
        state: 'ready',
        stale: false,
        checked_at: checkedAt,
        items: [
          {
            app_id: apps[0].app_id,
            installed_revision: revision,
            enabled: true,
            runtime_ai: true,
          },
        ],
      };
    else if (path.endsWith('/workspaces')) {
      const project = projects.find((item) => path.includes(item.id))!;
      body = {
        available: true,
        items: environments.filter((item) => item.project_id === project.id),
      };
    } else if (path.startsWith('/workbench/workspaces/')) {
      body = environments.find((item) => path.endsWith(item.id));
    } else if (path.endsWith('/usage'))
      body = {
        month: '2026-10',
        runtime_state: 'ready',
        stale: false,
        runtime_checked_at: checkedAt,
        development_tokens: 42000,
        unreported_tasks: 0,
        runtime: {
          total_tokens: 8000,
          app_opens: 24,
          complete: true,
          unreported_calls: 0,
        },
        budget: {
          version: 1,
          development_tokens: 100000,
          runtime_tokens: 50000,
          amount_minor: null,
          currency: 'KRW',
        },
        alerts: [],
      };
    else if (path.endsWith('/maintenance'))
      body = [
        {
          id: 'example-patch',
          app_id: apps[0].app_id,
          title: '일정 검색 결과 정리',
          notes: '담당자 필터와 검색 결과의 정렬을 개선합니다.',
          owner: '담당자',
          due_on: '2026-10-20',
          state: 'planned',
          version: 1,
          task_id: null,
          target_revision: null,
        },
      ];
    else if (path === '/workbench/platform')
      body = {
        git: { head: revision },
        gitlab: {
          state: 'ready',
          stale: false,
          pipelines: [{ revision, status: 'success' }],
        },
      };
    else throw new Error(`Unexpected browse request: ${path}`);
    await request.fulfill({ json: body });
  });
  await page.goto(`./?view=${route}`);
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.locator('.wb-browser')).toBeVisible();
  return mutations;
}

test('Studio uses one sidebar and a full-width project gallery before opening a project', async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const mutations = await browse(page, 'studio');
  const list = page.getByRole('group', { name: '프로젝트 목록' });
  const detail = page.getByRole('region', { name: '선택한 프로젝트' });
  await expect(page.locator('.console-shell > aside')).toHaveCount(1);
  await expect(page.getByRole('main').getByRole('complementary')).toHaveCount(
    0,
  );
  await expect(detail).toHaveCount(0);
  const cards = list.locator('.wb-card-title');
  await expect(cards).toHaveCount(2);
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  expect(second!.x).toBeGreaterThan(first!.x + first!.width);
  expect(second!.y).toBe(first!.y);
  await page.screenshot({ path: testInfo.outputPath('studio-desktop.png') });
  await cards.nth(0).click();
  await expect(
    detail.getByRole('heading', { name: projects[0].title }),
  ).toBeVisible();
  await expect(
    detail.getByRole('region', { name: '개발 작업 환경' }),
  ).toBeVisible();
  await expect(list).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('studio-detail.png') });
  await page.getByRole('button', { name: '목록으로 돌아가기' }).click();
  await expect(cards.nth(0)).toBeFocused();
  await list.getByRole('button', { name: /지원서 검토/ }).click();
  await expect(
    detail.getByRole('heading', { name: projects[1].title }),
  ).toBeVisible();
  await expect(
    detail.getByRole('heading', { name: projects[0].title }),
  ).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`project=${projects[1].id}`));
  await page.reload();
  await expect(
    detail.getByRole('heading', { name: projects[1].title }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
});

test('legacy environment links restore their project and selected environment', async ({
  page,
}) => {
  const second = {
    ...workspace(projects[0]),
    id: '44444444-4444-4444-8444-444444444444',
    title: '선택한 두 번째 개발 환경',
  };
  const mutations = await browse(page, `studio&environment=${second.id}`, [
    ...projects.map(workspace),
    second,
  ]);
  const detail = page.getByRole('region', { name: '선택한 프로젝트' });
  await expect(
    detail.getByRole('heading', { name: projects[0].title }),
  ).toBeVisible();
  await expect(page.getByLabel('개발 작업 환경 선택')).toHaveValue(second.id);
  await expect(
    page
      .getByRole('region', { name: '작업 환경 상세', exact: true })
      .getByText(second.title, { exact: true }),
  ).toBeVisible();
  const params = new URL(page.url()).searchParams;
  expect(params.get('project')).toBe(projects[0].id);
  expect(params.get('environment')).toBe(second.id);
  await page.reload();
  await expect(page.getByLabel('개발 작업 환경 선택')).toHaveValue(second.id);
  await expect(
    page
      .getByRole('region', { name: '작업 환경 상세', exact: true })
      .getByText(second.title, { exact: true }),
  ).toBeVisible();
  expect(mutations).toEqual([]);
});

test('app management separates its gallery from a full-width detail page with named sections', async ({
  page,
}, testInfo) => {
  const mutations = await browse(page, 'apps&app=calendar-helper');
  const detail = page.getByRole('region', { name: '선택한 앱' });
  for (const [tab, name] of [
    ['개요', '설치와 릴리스'],
    ['연결 설정', '소스와 연결 정보'],
    ['문제 관리', '문제·패치 관리'],
    ['작업 결과', '작업 기록'],
    ['사용량·예산', '월별 사용량·예산'],
  ]) {
    await detail.getByRole('button', { name: tab, exact: true }).click();
    await expect(
      detail.getByRole('region', { name, exact: true }),
    ).toBeVisible();
  }
  await expect(detail.locator('.wb-usage .wb-facts dd').first()).toContainText(
    '42,000',
  );
  await expect(page.getByRole('main').getByRole('complementary')).toHaveCount(
    0,
  );
  await expect(page.getByRole('group', { name: '앱 목록' })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('apps-detail.png') });
  await page.getByRole('button', { name: '목록으로 돌아가기' }).click();
  const list = page.getByRole('group', { name: '앱 목록' });
  await expect(list.locator('.wb-card-title')).toHaveCount(28);
  await expect(detail).toHaveCount(0);
  const before = await page.locator('#console-sidebar').boundingBox();
  await page.getByRole('main').evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  const after = await page.locator('#console-sidebar').boundingBox();
  expect(after).toEqual(before);
  await page.getByRole('main').evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({ path: testInfo.outputPath('apps-desktop.png') });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(mutations).toEqual([]);
});

test('mobile uses the same gallery and restores card focus after viewing details', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const mutations = await browse(page, 'studio');
  const library = page.getByRole('region', { name: '앱과 프로젝트 목록' });
  await expect(library).toBeVisible();
  await expect(page.getByRole('main').getByRole('complementary')).toHaveCount(
    0,
  );
  await page.screenshot({ path: testInfo.outputPath('studio-mobile.png') });
  await library.getByRole('button', { name: /지원서 검토/ }).click();
  await expect(
    page.getByRole('region', { name: '선택한 프로젝트' }),
  ).toBeFocused();
  await expect(library).toHaveCount(0);
  await page.getByRole('button', { name: '목록으로 돌아가기' }).click();
  await expect(
    library.getByRole('button', { name: /지원서 검토/ }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await library.getByRole('button', { name: /앱 목록/ }).click();
  await page.getByLabel('앱 찾기').fill('결과 없는 검색');
  await expect(page.getByText('일치하는 앱이 없습니다')).toBeVisible();
  await page.getByRole('button', { name: '검색 지우기' }).click();
  await expect(
    library.getByRole('button', { name: /일정 도우미/ }),
  ).toBeVisible();
  expect(mutations).toEqual([]);
});
