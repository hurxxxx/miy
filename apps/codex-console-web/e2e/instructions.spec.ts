import { expect, test } from '@playwright/test';

test('edits official documents, keeps drafts, detects conflicts, and asks Codex in a new session', async ({
  page,
}) => {
  await page.goto('./?view=instructions');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '지침·스킬', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '문서 만들기' }).click();
  await page
    .getByRole('dialog')
    .getByLabel('문서 경로')
    .fill('module/AGENTS.override.md');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: '문서 열기' })
    .click();
  const editor = page.getByLabel('문서 내용', { exact: true });
  const content = '# Scoped rules\n\nKeep the requested scope.  \n';
  await editor.fill(content);
  await page.getByRole('button', { name: '문서 저장', exact: true }).click();
  await expect(
    page.getByRole('status').filter({ hasText: '저장했습니다' }),
  ).toBeVisible();
  await page.reload();
  await page
    .getByRole('navigation', { name: '에이전트 참조 문서' })
    .getByRole('button', { name: 'module/AGENTS.override.md' })
    .click();
  await expect(editor).toHaveValue(content);
  const draft = content + '\nMy draft\n';
  await editor.fill(draft);
  await expect(
    page.getByRole('button', { name: 'Codex에 수정 요청' }),
  ).toBeDisabled();
  const nav = page.getByRole('navigation', { name: '콘솔 메뉴' });
  await nav.getByRole('button', { name: '작업 템플릿', exact: true }).click();
  await nav.getByRole('button', { name: '지침·스킬', exact: true }).click();
  await expect(editor).toHaveValue(draft);
  const cookie = (await page.context().cookies()).find(
    (c) => c.name === 'codex_console_csrf',
  )!;
  const documentURL = 'api/instructions/document';
  const original = await (
    await page.request.get(
      `${documentURL}?scope=project&path=module%2FAGENTS.override.md`,
    )
  ).json();
  const external = 'External edit\n';
  const mutation = await page.request.put(documentURL, {
    headers: {
      Origin: new URL(page.url()).origin,
      'X-CSRF-Token': decodeURIComponent(cookie.value),
    },
    data: {
      scope: original.scope,
      path: original.path,
      revision: original.revision,
      content: external,
    },
  });
  expect(mutation.ok()).toBe(true);
  await page.getByRole('button', { name: '문서 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    '다른 곳에서 문서가 변경되었습니다',
  );
  await expect(editor).toHaveValue(draft);
  await page
    .getByRole('button', { name: '최신 버전 확인 후 내 초안 유지' })
    .click();
  await expect(page.getByLabel('최신 저장 내용')).toHaveValue(external);
  await page
    .getByRole('button', { name: '이 버전을 기준으로 내 초안 유지' })
    .click();
  await page.getByRole('button', { name: '문서 저장', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Codex에 수정 요청' }),
  ).toBeEnabled();
  await page.getByRole('button', { name: 'Codex에 수정 요청' }).click();
  const requestDialog = page.getByRole('dialog');
  await requestDialog
    .getByLabel('수정할 내용')
    .fill('Propose clearer scoped instructions.');
  const submission = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      /\/api\/tasks\/[0-9a-f-]+\/messages$/.test(new URL(r.url()).pathname),
  );
  await requestDialog.getByRole('button', { name: '요청 보내기' }).click();
  const response = await submission;
  expect(response.status()).toBe(200);
  const payload = response.request().postDataJSON();
  expect(payload.stage).toBe('plan');
  expect(payload.permissions).toBe('ask');
  expect(payload.text).toContain('module/AGENTS.override.md');
  expect(payload.text).toContain('Propose clearer scoped instructions.');
  await expect(page).toHaveURL(/task=[0-9a-f-]+/);
  await expect(requestDialog).not.toBeVisible();
  await expect(page.getByLabel('현재 실행 상태')).toContainText('준비됨');
  await nav.getByRole('button', { name: '지침·스킬', exact: true }).click();
  await page.getByRole('button', { name: 'Codex에 수정 요청' }).click();
  await requestDialog
    .getByLabel('수정할 내용')
    .fill('Improve this document within the stated scope.');
  await requestDialog.getByLabel('실행 모드').selectOption('implement');
  const implementation = page.waitForResponse(
    (r) =>
      r.request().method() === 'POST' &&
      /\/api\/tasks\/[0-9a-f-]+\/implement$/.test(new URL(r.url()).pathname),
  );
  await requestDialog.getByRole('button', { name: '요청 보내기' }).click();
  const implemented = await implementation;
  expect(implemented.status()).toBe(200);
  expect(implemented.request().postDataJSON().permissions).toBe('ask');
  expect(implemented.request().postDataJSON().text).toContain('Please edit');
  await expect(page).toHaveURL(/task=[0-9a-f-]+/);
  await expect(requestDialog).not.toBeVisible();
});

test('creates a discoverable skill, metadata, and references without outer scrolling on mobile', async ({
  page,
}) => {
  await page.goto('./?view=instructions');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '문서 만들기' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('문서 종류').selectOption('skill');
  const name = `console-skill-${Date.now()}`;
  await dialog.getByLabel('문서 경로').fill(`.agents/skills/${name}/SKILL.md`);
  await dialog.getByRole('button', { name: '문서 열기' }).click();
  await expect(page.getByLabel('문서 내용', { exact: true })).toContainText(
    `name: ${name}`,
  );
  await page.getByRole('button', { name: '문서 저장', exact: true }).click();
  await expect(
    page.getByRole('status').filter({ hasText: '저장했습니다' }),
  ).toBeVisible();
  for (const [kind, suffix, content] of [
    [
      'metadata',
      'agents/openai.yaml',
      'policy:\n  allow_implicit_invocation: false\n',
    ],
    ['reference', 'references/guide.md', '# Skill reference\n'],
  ]) {
    await page.getByRole('button', { name: '문서 만들기' }).click();
    await dialog.getByLabel('문서 종류').selectOption(kind);
    await dialog
      .getByLabel('문서 경로')
      .fill(`.agents/skills/${name}/${suffix}`);
    await dialog.getByRole('button', { name: '문서 열기' }).click();
    await page.getByLabel('문서 내용', { exact: true }).fill(content);
    await page.getByRole('button', { name: '문서 저장', exact: true }).click();
    await expect(
      page.getByRole('status').filter({ hasText: '저장했습니다' }),
    ).toBeVisible();
  }
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿', exact: true })
    .click();
  await page.getByRole('button', { name: '템플릿 만들기' }).click();
  await expect(dialog.getByLabel(name, { exact: true })).toBeVisible();
  await expect(dialog.getByLabel(name, { exact: true })).not.toBeChecked();
  await expect(dialog).toContainText('체크하지 않아도');
  await dialog.getByLabel(name, { exact: true }).check();
  await expect(dialog.getByLabel(name, { exact: true })).toBeChecked();
  await dialog.getByRole('button', { name: '닫기', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 720 });
  await page.goto('./?view=instructions');
  await expect(
    page.getByRole('heading', { name: '지침·스킬', exact: true }),
  ).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    height: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
    width: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(dimensions.height).toBeLessThanOrEqual(dimensions.viewportHeight);
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewportWidth);
});
