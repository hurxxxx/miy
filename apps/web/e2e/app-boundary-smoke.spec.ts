import { expect, test, type Page } from '@playwright/test';
import { APP_CONTRACTS } from '@miy/contracts/app-contracts';
import { buildAppHref } from '@miy/contracts/app-routes';
import {
  FAKE_PLATFORM_ADMIN_USER,
  stubConversationsApi,
  stubShellBackend,
  stubAppDataBackend,
} from './helpers';

function collectBrowserErrors(page: Page) {
  const consoleErrors: string[] = [];
  const failedApiResponses: string[] = [];
  const pageErrors: string[] = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status >= 400 && response.url().includes('/api/')) {
      failedApiResponses.push(`${status} ${response.url()}`);
    }
  });

  return {
    expectClean() {
      expect(pageErrors, 'page errors').toEqual([]);
      expect(failedApiResponses, 'failed API responses').toEqual([]);
      expect(consoleErrors, 'console errors').toEqual([]);
    },
  };
}

async function stubFullShell(page: Page) {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
}

async function stubStructuralShell(page: Page) {
  const unhandled: string[] = [];
  await page.route(
    (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
    (route) => {
      unhandled.push(new URL(route.request().url()).pathname);
      return route.fulfill({
        status: 503,
        json: { detail: 'unstubbed structural request' },
      });
    },
  );
  await stubFullShell(page);
  return unhandled;
}

test.describe('AI-friendly app boundary smoke', () => {
  test('waits for the embedded memo autosave before a document link leaves', async ({
    page,
  }) => {
    const unhandled = await stubStructuralShell(page);
    const errors = collectBrowserErrors(page);
    let savedBody: string | null = null;
    let acknowledge!: () => void;
    const acknowledgement = new Promise<void>((resolve) => {
      acknowledge = resolve;
    });
    await page.route('**/api/v1/personal-widgets/memo', async (route) => {
      if (route.request().method() === 'PUT') {
        savedBody = route.request().postDataJSON().body;
        await acknowledgement;
      }
      await route.fulfill({
        json: {
          id: null,
          body: savedBody ?? '',
          createdAt: null,
          updatedAt: null,
        },
      });
    });
    await page.goto('/');
    const widget = page.frameLocator('iframe[src="/official-suite/widgets"]');
    await widget.getByRole('button', { name: /메모 열기|Open memo/ }).click();
    const memo = widget.getByRole('textbox', {
      name: /개인 메모|Personal memo/,
    });
    await memo.fill('Synthetic pending memo');
    // The open memo panel legitimately overlaps the launcher card. Keyboard
    // activation exercises the real captured link without forcing a hit area.
    await page.locator('a[href="/apps/docs"]').focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/$/);
    await expect(memo).toHaveValue('Synthetic pending memo');
    await expect.poll(() => savedBody).toBe('Synthetic pending memo');
    await expect(page).toHaveURL(/\/$/);
    acknowledge();
    await expect(page).toHaveURL(/\/apps\/docs$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /All Docs|전체 문서/ }),
    ).toBeVisible();
    expect(unhandled).toEqual([]);
    errors.expectClean();
  });

  test('includes the actual widget task-detail body portal in the iframe hit area', async ({
    page,
  }) => {
    const unhandled = await stubStructuralShell(page);
    const errors = collectBrowserErrors(page);
    // Only enough synthetic data to open the existing modal; no task workflow.
    const task = {
      archived: false,
      assignee_id: null,
      assignee_ids: [],
      assignee_name: null,
      assignee_names: [],
      board_position: 1,
      checklist_done: 0,
      checklist_total: 0,
      comments_count: 0,
      completed_date: null,
      description: '',
      description_blocks: null,
      due_date: null,
      follower_ids: [],
      follower_names: [],
      id: 'structural-task',
      labels: [],
      list_id: 'structural-list',
      milestone_id: null,
      milestone_title: null,
      parent_id: null,
      priority: 'medium',
      priority_label: 'Medium',
      progress: 0,
      recurrence_rule: null,
      reference: 'STRUCT-1',
      reporter_id: 'synthetic-user',
      reporter_name: 'Synthetic user',
      start_date: null,
      status: 'todo',
      status_label: 'Todo',
      subtask_count: 0,
      title: 'Synthetic modal surface',
      updated_at: '2026-10-10T00:00:00Z',
    };
    await page.route(
      '**/api/v1/personal-widgets/pms/tasks/assigned**',
      (route) =>
        route.fulfill({
          json: { items: [task], total: 1, page: 1, page_size: 100 },
        }),
    );
    await page.route('**/api/v1/pms/lists**', (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: 'structural-list',
              name: 'Synthetic list',
              role: 'viewer',
              team_id: null,
              team_name: null,
              folder_id: null,
              folder_name: null,
              status_mode: 'inherit',
            },
          ],
          total: 1,
          page: 1,
          page_size: 100,
        },
      }),
    );
    await page.route('**/api/v1/pms/lists/structural-list/statuses', (route) =>
      route.fulfill({ json: { items: [] } }),
    );
    await page.route('**/api/v1/pms/tasks/structural-task', (route) =>
      route.fulfill({
        json: {
          task,
          attachments: [],
          checklist_items: [],
          comments: [],
          linked_docs: [],
          subtasks: [],
        },
      }),
    );
    await page.route(
      '**/api/v1/pms/tasks/structural-task/activity-logs**',
      (route) =>
        route.fulfill({
          json: { items: [], total: 0, page: 1, page_size: 50 },
        }),
    );
    await page.route('**/api/v1/recording/recordings**', (route) =>
      route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } }),
    );
    await page.goto('/');
    const frame = page.locator('iframe[src="/official-suite/widgets"]');
    const widget = page.frameLocator('iframe[src="/official-suite/widgets"]');
    await widget.getByRole('button', { name: /PMS 열기|Open PMS/ }).click();
    await widget
      .getByRole('button', {
        name: /Synthetic modal surface 상세 열기|Open Synthetic modal surface details/,
      })
      .click();
    await expect(widget.locator('[data-ui-overlay]')).toBeVisible();
    await expect
      .poll(() =>
        frame.evaluate((element) => {
          return (
            document.elementFromPoint(5, 5) === element &&
            document.elementFromPoint(5, window.innerHeight - 5) === element
          );
        }),
      )
      .toBe(true);
    // The backdrop is outside the dock's narrow rectangle and must be clickable.
    await widget
      .locator('[data-ui-overlay] > button')
      .click({ position: { x: 5, y: 5 } });
    await expect(widget.locator('[data-ui-overlay]')).toHaveCount(0);
    expect(unhandled).toEqual([]);
    errors.expectClean();
  });

  test('preserves first-party document navigation and the shared widget session', async ({
    page,
  }) => {
    const unhandledApi: string[] = [];
    const authProbes: Array<{ widget: boolean; sharedToken: boolean }> = [];
    // Unknown requests must remain inside this synthetic test boundary.
    await page.route(
      (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
      (route) => {
        unhandledApi.push(new URL(route.request().url()).pathname);
        return route.fulfill({
          status: 503,
          json: { detail: 'unstubbed structural request' },
        });
      },
    );
    await stubFullShell(page);
    page.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/v1/auth/me') {
        authProbes.push({
          widget: request.frame().url().includes('/official-suite/widgets'),
          sharedToken:
            request.headers().authorization === 'Bearer e2e-test-token',
        });
      }
    });
    const errors = collectBrowserErrors(page);
    await page.goto('/');
    await expect(
      page.getByRole('heading', { level: 1, name: /앱 런처|App launcher/ }),
    ).toBeVisible();
    const widget = page.frameLocator('iframe[src="/official-suite/widgets"]');
    await expect(
      widget.locator('[data-miy-embedded-surface]').first(),
    ).toBeVisible();
    await expect
      .poll(() => authProbes.some((probe) => probe.widget && probe.sharedToken))
      .toBe(true);
    expect(authProbes.some((probe) => !probe.widget && probe.sharedToken)).toBe(
      true,
    );
    await page.evaluate(() => {
      (
        window as Window & { structuralDocumentMarker?: boolean }
      ).structuralDocumentMarker = true;
    });
    await page.locator('a[href="/apps/docs"]').click();
    await expect(page).toHaveURL(/\/apps\/docs$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /All Docs|전체 문서/ }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          (window as Window & { structuralDocumentMarker?: boolean })
            .structuralDocumentMarker,
      ),
    ).toBeUndefined();
    await expect(
      page.locator(
        'script[type="module"][src*="/official-suite/src/main.tsx"]',
      ),
    ).toHaveCount(1);
    expect(
      await page.evaluate(() => localStorage.getItem('miy.auth.token')),
    ).toBe('e2e-test-token');
    expect(unhandledApi).toEqual([]);
    errors.expectClean();
  });

  test('opens admitted apps directly from the company launcher', async ({
    page,
  }) => {
    await stubFullShell(page);
    const errors = collectBrowserErrors(page);

    await page.goto('/');
    await expect(
      page.getByRole('heading', { level: 1, name: /앱 런처|App launcher/ }),
    ).toBeVisible();
    await page.locator('a[href="/apps/docs"]').click();
    await expect(page).toHaveURL(/\/apps\/docs$/);
    await expect(page.getByText(/^(실행 범위|Execution scope)$/)).toHaveCount(
      0,
    );
    await page.goto('/apps/planner');
    await expect(page).toHaveURL(/\/apps\/planner$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /Planner|플래너/ }),
    ).toBeVisible();
    const clocks = page.getByRole('group', {
      name: /도시별 현재 시간|Current times by city/,
    });
    const cities = [
      /한국 시간 \(KST\)|Korea time \(KST\)/,
      /미국 뉴욕 시간|New York, US time/,
      /독일 베를린 시간|Berlin, Germany time/,
    ];
    for (const city of cities) {
      await expect(
        clocks.getByText(city).locator('..').locator('time'),
      ).toHaveText(/\d{2}:\d{2}:\d{2}/);
    }
    await page.setViewportSize({ width: 360, height: 740 });
    for (const city of cities) {
      const bounds = await clocks.getByText(city).locator('..').boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds!.x).toBeGreaterThanOrEqual(0);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(360);
    }
    errors.expectClean();
  });

  test('does not fetch app data when admission is denied', async ({ page }) => {
    const deniedRequests: string[] = [];
    await page.route(
      (url) => url.pathname === '/api' || url.pathname.startsWith('/api/'),
      (route) =>
        route.fulfill({
          status: 503,
          json: { detail: 'unstubbed structural request' },
        }),
    );
    page.on('request', (request) => {
      if (new URL(request.url()).pathname.startsWith('/api/v1/meeting/'))
        deniedRequests.push(request.url());
    });
    await stubShellBackend(page, { enabledAppIds: ['home'] });
    await page.goto('/apps/meeting');
    await expect(
      page.getByRole('heading', { name: /접근 권한 없음|No access/ }),
    ).toBeVisible();
    expect(deniedRequests).toEqual([]);
  });

  test('renders company apps and tool wrappers through the shell registry', async ({
    page,
  }) => {
    await stubFullShell(page);
    const errors = collectBrowserErrors(page);

    const routes: Array<{
      path: string;
      assert: (page: Page) => Promise<void>;
    }> = [
      {
        path: '/apps/home',
        assert: async (current) => {
          await expect(current.getByText(/Good/)).toBeVisible();
        },
      },
      {
        path: '/apps/chatbot',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', {
              name: /AI 어시스턴트 챗봇|AI Assistant Chatbot/,
            }),
          ).toBeVisible();
        },
      },
      {
        path: '/apps/pms',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', { name: 'PMS', exact: true }).or(
              current.getByRole('heading', {
                name: /^(No Spaces Yet|아직 스페이스가 없습니다)$/,
              }),
            ),
          ).toBeVisible();
          await expect(
            current
              .getByRole('link', { name: /Assigned to me|내게 배정됨/ })
              .or(
                current.getByRole('button', {
                  name: /Create Space|스페이스 만들기/,
                }),
              )
              .first(),
          ).toBeVisible();
        },
      },
      {
        path: '/apps/docs',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', {
              level: 1,
              name: /All Docs|전체 문서/,
            }),
          ).toBeVisible();
          await expect(
            current.getByRole('button', { name: /New Doc|새 Doc/ }).first(),
          ).toBeVisible();
        },
      },
      {
        path: '/apps/planner',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', { level: 1, name: /Planner|플래너/ }),
          ).toBeVisible();
          await expect(
            current.getByRole('button', { name: /Calendar|캘린더/ }),
          ).toBeVisible();
        },
      },
      {
        path: '/apps/meeting',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', { level: 1, name: /Meetings|회의/ }),
          ).toBeVisible();
          await expect(
            current
              .getByRole('button', { name: /New Meeting|새 회의/ })
              .first(),
          ).toBeVisible();
        },
      },
      {
        path: '/apps/retrieval-search',
        assert: async (current) => {
          await expect(
            current.getByRole('heading', {
              level: 1,
              name: /Retrieval 진단 검색|Retrieval diagnostics search/,
            }),
          ).toBeVisible();
        },
      },
    ];

    for (const route of routes) {
      await page.goto(route.path);
      await expect(page).toHaveURL(
        new RegExp(`${route.path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
      );
      await route.assert(page);
    }

    errors.expectClean();
  });

  test('mounts every executable app entry without falling through to NotFoundView', async ({
    context,
  }) => {
    test.setTimeout(120_000);
    for (const app of APP_CONTRACTS) {
      await test.step(app.app_id, async () => {
        const appPage = await context.newPage();
        try {
          await stubAppDataBackend(appPage);
          await stubShellBackend(appPage, {
            enabledAppIds: APP_CONTRACTS.map((contract) => contract.app_id),
          });
          await stubConversationsApi(appPage);

          const href = buildAppHref({
            routeId: app.entry_route_id,
          });
          await appPage.goto(href, { waitUntil: 'domcontentloaded' });
          await expect(appPage).toHaveURL(
            new RegExp(`${href.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`),
          );
          await expect(
            appPage.getByRole('navigation', {
              name: /주요 앱 탐색|Primary app navigation/,
            }),
          ).toBeVisible();
          await expect(
            appPage.getByRole('heading', {
              name: /페이지를 찾을 수 없습니다|Page not found/,
            }),
            app.app_id,
          ).toHaveCount(0);
        } finally {
          await appPage.close();
        }
      });
    }
  });

  test('opens a newly created Bento presentation on its canonical detail route', async ({
    page,
  }) => {
    await stubFullShell(page);
    let creations = 0;
    // This smoke owns shell composition and routing. Keep the external editor
    // out of its network boundary; bridge behavior has its own protocol tests.
    await page.route('**/*', (route) => {
      const request = route.request();
      if (
        request.resourceType() === 'document' &&
        request.frame().parentFrame()
      )
        return route.fulfill({
          contentType: 'text/html',
          body: '<!doctype html><title>Editor fixture</title>',
        });
      return route.fallback();
    });
    const document = {
      id: 'presentation-1',
      title: 'Untitled Presentation',
      visibility: 'personal',
      version: 1,
      created_by_id: 'user-e2e',
      created_by_name: 'E2E Tester',
      created_at: '2026-08-31T00:00:00Z',
      updated_at: '2026-08-31T00:00:00Z',
      archived_at: null,
      can_edit: true,
      can_manage: true,
      document_json: '{}',
    };
    await page.route('**/api/v1/bento/**', (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (pathname.endsWith('/bento/hub')) {
        return route.fulfill({
          json: { items: [], view: 'all', page: 1, page_size: 200, total: 0 },
        });
      }
      if (pathname.endsWith('/bento/ai-jobs')) {
        return route.fulfill({ json: [] });
      }
      if (pathname.endsWith('/bento/items') && request.method() === 'POST') {
        creations++;
        return route.fulfill({ json: document });
      }
      if (pathname.endsWith('/bento/items/presentation-1')) {
        return route.fulfill({ json: document });
      }
      return route.fulfill({ status: 404, json: { detail: 'not stubbed' } });
    });

    await page.goto('/apps/bento');
    await page
      .getByRole('button', { name: /새 프레젠테이션|New presentation/ })
      .first()
      .click();

    await expect(page).toHaveURL(
      /\/apps\/bento\/presentations\/presentation-1$/,
    );
    await expect(
      page.getByRole('heading', {
        name: /페이지를 찾을 수 없습니다|Page not found/,
      }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('heading', { name: document.title, exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(
      page.getByRole('heading', { name: document.title, exact: true }),
    ).toHaveText(document.title);
    await test.info().attach('mobile-toolbar-layout', {
      body: JSON.stringify(
        await page
          .getByRole('heading', { name: document.title, exact: true })
          .evaluate((heading) => ({
            heading: heading.getBoundingClientRect().toJSON(),
            toolbar: heading.parentElement?.getBoundingClientRect().toJSON(),
            children: Array.from(heading.parentElement?.children ?? []).map(
              (child) => ({
                tag: child.tagName,
                box: child.getBoundingClientRect().toJSON(),
              }),
            ),
          })),
      ),
      contentType: 'application/json',
    });
    await expect(
      page.getByRole('heading', { name: document.title, exact: true }),
    ).toBeVisible();
    const toolbar = page
      .getByRole('heading', { name: document.title, exact: true })
      .locator('..');
    await expect
      .poll(() =>
        page
          .getByRole('heading', { name: document.title, exact: true })
          .evaluate((heading) => heading.getBoundingClientRect().width),
      )
      .toBeGreaterThan(80);
    expect(
      await toolbar.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
    expect(creations).toBe(1);
  });

  test('keeps Bento admission ahead of its moved business data', async ({
    page,
  }) => {
    await stubAppDataBackend(page);
    await stubShellBackend(page, { enabledAppIds: ['home'] });
    await stubConversationsApi(page);
    let reads = 0;
    await page.route('**/api/v1/bento/**', (route) => {
      reads++;
      return route.fulfill({ status: 403, json: { detail: 'denied' } });
    });
    await page.goto('/apps/bento/presentations/private-presentation');
    await expect(
      page.getByRole('heading', { name: '접근 권한 없음' }),
    ).toBeVisible();
    expect(reads).toBe(0);
  });

  test('keeps denied apps blocked before their data loads', async ({
    page,
  }) => {
    await stubAppDataBackend(page);
    await stubShellBackend(page, {
      enabledAppIds: ['home', 'chatbot', 'docs', 'planner', 'pms'],
    });
    await stubConversationsApi(page);
    const errors = collectBrowserErrors(page);

    await page.goto('/apps/meeting');

    await expect(
      page.getByRole('heading', { name: '접근 권한 없음' }),
    ).toBeVisible();
    await expect(
      page.getByText('현재 계정은 이 앱을 사용할 수 없습니다.'),
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'MEETING' })).toHaveCount(0);
    errors.expectClean();
  });

  test('keeps legacy top-level app paths on NotFoundView', async ({ page }) => {
    await stubFullShell(page);
    const errors = collectBrowserErrors(page);

    for (const path of ['/meeting', '/docs', '/pms', '/chatbot']) {
      await page.goto(path);
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(
        page.getByRole('heading', { name: '페이지를 찾을 수 없습니다' }),
      ).toBeVisible();
    }

    errors.expectClean();
  });

  test('renders admin sections for platform admin through settings boundaries', async ({
    page,
  }) => {
    await stubAppDataBackend(page);
    await stubShellBackend(page, { user: FAKE_PLATFORM_ADMIN_USER });
    const errors = collectBrowserErrors(page);

    await page.goto('/admin/general');
    await expect(
      page.locator('main').getByRole('heading', { level: 1 }),
    ).toBeVisible();

    await page.goto('/admin/groups');
    await expect(
      page.locator('main').getByRole('heading', { level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', {
        name: /^(그룹 생성|Create group)$/,
      }),
    ).toBeVisible();

    errors.expectClean();
  });
});
