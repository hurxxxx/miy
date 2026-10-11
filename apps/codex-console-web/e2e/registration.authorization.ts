import { expect, test, type Page } from '@playwright/test';

// Real WB password/CSRF/session, SQLite, source snapshots, vault and HTTP callback.
// Only Core approval/exchange/receipt and native RPC are synthetic fixture services.
async function login(page: Page) {
  await page.goto('./?view=studio');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '새 앱 프로젝트', exact: true }),
  ).toBeVisible();
  const csrf = (await page.context().cookies()).find(
    (c) => c.name === 'codex_console_csrf',
  )?.value;
  if (!csrf) throw new Error('Missing synthetic session CSRF');
  return { origin: new URL(page.url()).origin, 'x-csrf-token': csrf };
}

async function task(page: Page) {
  const headers = await login(page);
  const fixture = await (
    await page.request.get('__test__/registration-fixture')
  ).json();
  const catalog = await (
    await page.request.get('api/workbench/catalog')
  ).json();
  if (
    !catalog.projects.some(
      (row: { app_id: string }) => row.app_id === 'sample-app',
    )
  ) {
    const created = await page.request.post('api/workbench/projects', {
      headers,
      data: {
        app_id: 'sample-app',
        title: '등록 연결 검증',
        summary: '현재 저장된 앱을 개인 앱으로 등록한다.',
        reuse_decision: 'new',
        reuse_notes: '격리된 합성 앱 소스',
      },
    });
    expect(created.ok()).toBe(true);
  }
  if (
    !catalog.items.some(
      (row: { app_id: string; source_status: string }) =>
        row.app_id === 'sample-app' && row.source_status === 'ready',
    )
  ) {
    const bound = await page.request.put(
      'api/workbench/apps/sample-app/source',
      {
        headers,
        data: {
          repository_root: fixture.repository_root,
          version: 0,
        },
      },
    );
    expect(bound.ok()).toBe(true);
  }
  await page.reload();
  await page.getByRole('button', { name: '새 등록 작업', exact: true }).click();
  await expect(page).toHaveURL(/task=/);
  const taskId = new URL(page.url()).searchParams.get('task');
  if (!taskId) throw new Error('No registration task selected');
  const panel = page.getByRole('region', { name: '최초 앱 등록', exact: true });
  await expect(
    panel.getByText('등록 권한 연결이 필요합니다.', { exact: true }),
  ).toBeVisible();
  await panel
    .getByLabel('개발 앱 주소', { exact: true })
    .fill('https://preview.example.test');
  return { headers, fixture, taskId, panel };
}

async function approve(page: Page) {
  const panel = page.getByRole('region', { name: '최초 앱 등록', exact: true });
  await panel
    .getByRole('button', { name: '등록 권한 연결', exact: true })
    .click();
  const link = panel.getByRole('link', { name: 'MIY에서 승인', exact: true });
  await expect(link).toBeVisible();
  const popupPromise = page.waitForEvent('popup');
  await link.click();
  const popup = await popupPromise;
  await popup
    .getByRole('button', { name: 'Approve fixture registration', exact: true })
    .click();
  await popup.waitForURL(
    (url) =>
      url.origin === new URL(page.url()).origin && url.searchParams.has('task'),
  );
  return popup;
}

test('real Workbench callback retains the original session and observes the same historical registration', async ({
  page,
}) => {
  const { headers, fixture, taskId } = await task(page);
  const before = await (
    await page.request.get(`api/tasks/${taskId}/registration`)
  ).json();
  const popup = await approve(page);
  const panel = popup.getByRole('region', {
    name: '최초 앱 등록',
    exact: true,
  });
  await expect(
    panel.getByText('등록 권한이 연결되었습니다.', { exact: true }),
  ).toBeVisible();
  const connected = await (
    await page.request.get(`api/tasks/${taskId}/registration`)
  ).json();
  expect(connected.operation_id).toBe(before.operation_id);
  expect(connected.authorization_state).toBe('ready');
  const observed = await (
    await page.request.get('__test__/registration-fixture')
  ).json();
  expect(observed.callback_origin).toBe(fixture.issuer);
  expect(observed.callback_had_cookie).toBe(false);
  expect(observed.exchange_count).toBe(fixture.exchange_count + 1);
  const detail = await (await page.request.get(`api/tasks/${taskId}`)).text();
  expect(detail).not.toContain('miyrg_');
  expect(detail).not.toContain('miyrc_');
  expect(detail).not.toContain('code_verifier');
  expect(new URL(popup.url()).searchParams.has('code')).toBe(false);
  const seeded = await page.request.post(
    `__test__/registration-history/${taskId}`,
    { headers },
  );
  expect(seeded.ok()).toBe(true);
  const history = await seeded.json();
  await panel
    .getByRole('button', { name: '연결 상태 새로고침', exact: true })
    .click();
  await expect(
    panel.getByText('등록 응답을 확인하지 못했습니다.', { exact: false }),
  ).toBeVisible();
  await panel
    .getByRole('button', { name: '동일 등록 작업 결과 조회', exact: true })
    .click();
  await expect(
    panel.getByText('과거 등록 완료 기록입니다.', { exact: false }),
  ).toBeVisible();
  const recovered = await (
    await page.request.get(`api/tasks/${taskId}/registration`)
  ).json();
  expect(recovered.operation_id).toBe(before.operation_id);
  expect(recovered.receipt.source_revision).toBe(
    history.receipt.source_revision,
  );
  expect(recovered.state).toBe('registered');
  const settingsLink = panel.getByRole('link', {
    name: 'MIY에서 내 개발 미리보기 설정',
    exact: true,
  });
  await expect(settingsLink).toHaveAttribute(
    'href',
    `${fixture.issuer}/apps/${encodeURIComponent(recovered.receipt.app_id)}/installed/${encodeURIComponent(recovered.receipt.installation_id)}/setup`,
  );
  await expect(settingsLink).toHaveAttribute('target', '_blank');
  await expect(settingsLink).toHaveAttribute('rel', 'noopener noreferrer');
  const settingsHref = await settingsLink.getAttribute('href');
  if (!settingsHref) throw new Error('Missing owner preview settings link');
  const settingsURL = new URL(settingsHref);
  expect(settingsURL.search).toBe('');
  expect(settingsURL.hash).toBe('');
  expect(
    (await (await page.request.get('__test__/registration-fixture')).json())
      .receipt_count,
  ).toBe(observed.receipt_count + 1);
  await popup.close();
});

test('a consumed exchange response loss returns to the Task and reconnects without changing its operation', async ({
  page,
}) => {
  const { headers, fixture, taskId } = await task(page);
  const mode = await page.request.post('__test__/registration-mode', {
    headers,
    data: { mode: 'drop_exchange_once' },
  });
  expect(mode.ok()).toBe(true);
  const before = await (
    await page.request.get(`api/tasks/${taskId}/registration`)
  ).json();
  const failed = await approve(page);
  await expect(
    failed.getByText('등록 승인을 확인하지 못했습니다. 직접 다시 연결하세요.', {
      exact: true,
    }),
  ).toBeVisible();
  expect(
    (await (await page.request.get(`api/tasks/${taskId}/registration`)).json())
      .authorization_state,
  ).toBe('failed');
  await failed.close();
  const ready = await approve(page);
  await expect(
    ready.getByText('등록 권한이 연결되었습니다.', { exact: true }),
  ).toBeVisible();
  const recovered = await (
    await page.request.get(`api/tasks/${taskId}/registration`)
  ).json();
  expect(recovered.operation_id).toBe(before.operation_id);
  expect(recovered.state).toBe('unsubmitted');
  expect(
    (await (await page.request.get('__test__/registration-fixture')).json())
      .exchange_count,
  ).toBe(fixture.exchange_count + 2);
  await ready.close();
});

test('a new browser login cannot use an earlier registration authorization to start a turn', async ({
  page,
}) => {
  const { taskId } = await task(page);
  const popup = await approve(page);
  await expect(
    popup.getByText('등록 권한이 연결되었습니다.', { exact: true }),
  ).toBeVisible();
  await popup.close();
  await page.context().clearCookies();
  const headers = await login(page);
  await page.goto(`./?task=${taskId}`);
  await expect(
    page.getByText(
      '이 작업은 다른 로그인 세션에 연결되어 있습니다. 직접 다시 연결하세요.',
      { exact: true },
    ),
  ).toBeVisible();
  const denied = await page.request.post(`api/tasks/${taskId}/messages`, {
    headers,
    data: {
      text: 'Continue first registration',
      operation_id: crypto.randomUUID(),
    },
  });
  expect(denied.status()).toBe(403);
  expect((await denied.json()).code).toBe('registration_session_changed');
  const row = await (await page.request.get(`api/tasks/${taskId}`)).json();
  expect(row.thread_id).toBeNull();
  expect(row.turn_id).toBeNull();
});
