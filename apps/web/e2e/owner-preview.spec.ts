import { expect, test, type Page } from '@playwright/test';
import type { components } from '@miy/contracts/openapi.generated';
import {
  FAKE_COMPANY_USER,
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

type Preview = components['schemas']['OwnerPreviewOut'];
type Patch = components['schemas']['OwnerPreviewPatch'];
const installationId = 'b0000000-0000-4000-8000-000000000001';
const appId = 'private-notes';
const setupPath = `/apps/${appId}/installed/${installationId}/setup`;
const apiPath = `/api/v1/independent-apps/${appId}/installations/${installationId}/owner-preview`;
const initial: Preview = {
  schema_version: 1,
  app_id: appId,
  installation_id: installationId,
  owner_user_id: FAKE_COMPANY_USER.id,
  display_name: 'Synthetic private notes',
  origin: 'https://notes.example.test',
  generation: 1,
  definition_digest: `sha256:${'a'.repeat(64)}`,
  source_revision: 'b'.repeat(40),
  runtime_profile: 'web-api-postgres-v1',
  requested_permissions: ['identity:read', 'data:read', 'data:write'],
  granted_permissions: [],
  enabled: false,
  company_enabled: true,
  can_configure: true,
  unavailable_reason: null,
};

// Every API request is intercepted. The state below is only a synthetic server;
// neither owner settings nor app runtimes are changed by these browser tests.
async function fixture(page: Page, loseSaveResponse = false) {
  const unexpected: string[] = [];
  const errors: string[] = [];
  const patches: Patch[] = [];
  let reads = 0;
  let state: Preview = structuredClone(initial);
  let denied = false;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/**', (route) => {
    unexpected.push(
      `${route.request().method()} ${new URL(route.request().url()).pathname}`,
    );
    return route.fulfill({
      status: 501,
      json: { detail: 'No live API is allowed in this fixture' },
    });
  });
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['home'] });
  await stubConversationsApi(page);
  await page.route('**/api/v1/personal-widgets/pms/tasks/assigned**', (route) =>
    route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } }),
  );
  await page.route('**/api/v1/independent-apps/catalog**', (route) =>
    route.fulfill({
      json: {
        page: 1,
        page_size: 200,
        total: 1,
        catalog_revision: 'synthetic-disabled-owner-installation',
        items: [
          {
            definition: {
              owner_user_id: initial.owner_user_id,
              definition: {
                app_id: appId,
                ownership: 'personal',
                display: {
                  name: initial.display_name,
                  translations: {},
                  icon: 'app-window',
                },
                entrypoints: { ui: '/' },
              },
            },
            installations: [
              {
                id: installationId,
                app_id: appId,
                origin: initial.origin,
                environment: 'development',
                enabled: false,
                state: 'configured',
                generation: 1,
                launchable: false,
                ui_entrypoint: null,
              },
            ],
          },
        ],
      },
    }),
  );
  await page.route(`**${apiPath}`, async (route) => {
    const request = route.request();
    expect(request.headers().authorization).toBe('Bearer e2e-test-token');
    if (request.method() === 'GET') {
      reads += 1;
      return denied
        ? route.fulfill({ status: 403, json: { detail: 'Not the owner' } })
        : route.fulfill({ json: state });
    }
    expect(request.method()).toBe('PATCH');
    const patch = request.postDataJSON() as Patch;
    patches.push(patch);
    expect(denied).toBe(false);
    expect(state.can_configure).toBe(true);
    expect(patch.expected_generation).toBe(state.generation);
    expect(patch.expected_definition_digest).toBe(state.definition_digest);
    expect(patch.expected_source_revision).toBe(state.source_revision);
    state = {
      ...state,
      enabled: patch.enabled,
      granted_permissions: patch.granted_permissions,
      generation: state.generation + 1,
    };
    // Simulate a committed change whose response never reaches the browser.
    if (loseSaveResponse) return route.abort('failed');
    return route.fulfill({ json: state });
  });
  return {
    patches,
    errors,
    unexpected,
    reads: () => reads,
    state: () => state,
    replace: (next: Preview) => {
      state = next;
    },
    deny: () => {
      denied = true;
    },
  };
}

test('owned disabled installation opens read-only and saves only explicit generation-bound preview choices', async ({
  page,
}) => {
  const server = await fixture(page);
  await page.goto('/');
  const owned = page.getByRole('region', { name: '내 개발 설치', exact: true });
  await expect(owned.getByText(initial.display_name)).toBeVisible();
  const settings = owned.getByRole('link', { name: '개발 미리보기 설정' });
  await expect(settings).toHaveAttribute('href', setupPath);
  expect(server.reads()).toBe(0);
  expect(server.patches).toEqual([]);
  await settings.click();
  await expect(page).toHaveURL(new RegExp(`${setupPath}$`));
  await expect(
    page.getByRole('heading', { name: '개발 미리보기 설정' }),
  ).toBeVisible();
  await expect(page.getByLabel('내 개발 미리보기 허용')).not.toBeChecked();
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText('허용 설정은 앱 서버를 실행하거나 배포하지 않습니다.', {
      exact: false,
    }),
  ).toBeVisible();
  expect(server.reads()).toBeGreaterThan(0);
  expect(server.patches).toEqual([]);
  await page.getByLabel('내 개발 미리보기 허용').check();
  await page.getByLabel('내 기본 프로필 읽기').check();
  await page.getByLabel('이 앱에 저장한 내 데이터 읽기').check();
  expect(server.patches).toEqual([]);
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await expect(
    page.getByText('개발 미리보기 설정을 저장했습니다.', { exact: true }),
  ).toBeVisible();
  expect(server.patches).toEqual([
    {
      expected_generation: 1,
      expected_definition_digest: initial.definition_digest,
      expected_source_revision: initial.source_revision,
      enabled: true,
      granted_permissions: ['data:read', 'identity:read'],
    },
  ]);
  await page.reload();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeChecked();
  await expect(page.getByLabel('이 앱에 저장한 내 데이터 읽기')).toBeChecked();
  await expect(
    page.getByLabel('이 앱에 저장한 내 데이터 작성·수정·삭제'),
  ).not.toBeChecked();
  expect(server.patches).toHaveLength(1);
  expect(server.errors).toEqual([]);
  expect(server.unexpected).toEqual([]);
});

test('lost save response stays unknown until an explicit read and never automatically retries PATCH', async ({
  page,
}) => {
  const server = await fixture(page, true);
  await page.goto(setupPath);
  await expect(
    page.getByText(initial.display_name, { exact: true }),
  ).toBeVisible();
  await page.getByLabel('내 개발 미리보기 허용').check();
  await page.getByLabel('내 기본 프로필 읽기').check();
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    '저장 결과를 확인하지 못했습니다.',
  );
  await expect(page.getByRole('alert')).toContainText(
    '자동으로 다시 저장하지 않습니다.',
  );
  expect(server.state().enabled).toBe(true);
  expect(server.state().generation).toBe(2);
  expect(server.patches).toHaveLength(1);
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeDisabled();
  const priorReads = server.reads();
  await page.getByRole('button', { name: '현재 설정 다시 읽기' }).click();
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: '현재 설정을 다시 읽었습니다.' }),
  ).toBeVisible();
  await expect(
    page.getByText(
      '이 값만으로 앞선 저장 요청의 완료 여부를 확정하지는 않습니다.',
      { exact: false },
    ),
  ).toBeVisible();
  expect(server.reads()).toBe(priorReads + 1);
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeChecked();
  await expect(page.getByLabel('내 기본 프로필 읽기')).toBeChecked();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeEnabled();
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeChecked();
  expect(server.patches).toHaveLength(1);
  expect(server.errors).toEqual([]);
  expect(server.unexpected).toEqual([]);
});

test('company-disabled and deployed settings stay read-only and a denied owner read exposes no controls', async ({
  page,
}) => {
  const server = await fixture(page);
  server.replace({
    ...initial,
    company_enabled: false,
    can_configure: false,
    unavailable_reason: 'company_disabled',
  });
  await page.goto(setupPath);
  await expect(
    page.getByText(
      '플랫폼에서 이 앱의 사용을 중지해 현재 설정을 변경할 수 없습니다.',
    ),
  ).toBeVisible();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeDisabled();
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toBeDisabled();
  server.replace({
    ...initial,
    can_configure: false,
    unavailable_reason: 'already_deployed',
  });
  await page.getByRole('button', { name: '현재 설정 다시 읽기' }).click();
  await expect(
    page.getByText(
      '이 화면은 배포나 검증을 시작하기 전 설치에만 사용할 수 있습니다.',
      { exact: false },
    ),
  ).toBeVisible();
  await expect(page.getByLabel('내 개발 미리보기 허용')).toBeDisabled();
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toBeDisabled();
  server.deny();
  await page.reload();
  await expect(page.getByRole('alert')).toContainText(
    '이 계정에서 설정을 읽을 수 없습니다.',
  );
  await expect(
    page.getByText(initial.display_name, { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel('내 개발 미리보기 허용')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: '설정 저장', exact: true }),
  ).toHaveCount(0);
  expect(server.patches).toEqual([]);
  expect(server.errors).toEqual([]);
  expect(server.unexpected).toEqual([]);
});
