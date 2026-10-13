import { expect, test } from '@playwright/test';

test('browses tools and requests, verifies and retains a development merge in the same conversation', async ({
  page,
}) => {
  await page.goto('./?view=agent-tools');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Codex 도구', exact: true }),
  ).toBeVisible();
  await expect(page.locator('.tool-catalog-card')).toHaveCount(5);
  await page.getByLabel('도구 검색').fill('요약');
  await expect(page.locator('.tool-catalog-card')).toHaveCount(1);
  await page.getByText('도구 지침 · 입력 형식', { exact: true }).click();
  await expect(page.locator('.tool-catalog-card pre')).toContainText(
    'verify_merge',
  );
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === 'codex_console_csrf',
  )!.value;
  const headers = { origin: new URL(page.url()).origin, 'x-csrf-token': csrf };
  const created = await page.request.post('api/tasks', {
    headers,
    data: { title: '작업 타임라인 검증' },
  });
  const task = await created.json();
  await page.request.post(`api/tasks/${task.id}/messages`, {
    headers,
    data: { operation_id: crypto.randomUUID(), text: 'Inspect fixture' },
  });
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`api/tasks/${task.id}`)).json()).status,
    )
    .toBe('idle');
  const fixture = await (
    await page.request.post('__test__/questions-git', {
      headers,
      data: { task_id: task.id },
    })
  ).json();
  await page.request.post(`api/tasks/${task.id}/git-links`, {
    headers,
    data: { root: fixture.root },
  });
  await page.goto(`./?task=${task.id}`);
  const composer = page.getByLabel('요청 내용 입력');
  await composer.fill('보존할 후속 작업 초안');
  await page.getByRole('button', { name: '변경사항', exact: true }).click();
  const checkout = page
    .locator('.git-checkout')
    .filter({ hasText: fixture.root });
  const merge = checkout.getByRole('button', {
    name: '개발로 병합 요청',
    exact: true,
  });
  await expect(merge).toBeEnabled();
  await merge.click();
  await expect(
    page.getByRole('heading', { name: '한눈에 보는 작업 흐름', exact: true }),
  ).toBeVisible();
  await expect(page.locator('.work-summary')).not.toContainText(fixture.root);
  await page.getByText('단계별 상세 기록 · 실행 근거', { exact: true }).click();
  await expect(page.locator('.timeline-segment')).toHaveCount(1);
  await expect(page.locator('.timeline-segment')).toContainText(
    'Git 병합이 확인되지 않았습니다',
  );
  await expect(composer).toHaveValue('보존할 후속 작업 초안');
  const integrated = await page.request.post('__test__/integrate-timeline', {
    headers,
    data: { task_id: task.id },
  });
  expect(integrated.ok()).toBe(true);
  await page
    .getByRole('button', { name: '병합 결과 확인', exact: true })
    .click();
  await expect(page.locator('.timeline-segment')).toContainText(
    'Git 병합 확인 완료',
  );
  await expect(page.locator('.timeline-segment')).toContainText(
    '브라우저 테스트에서 병합 흐름과 작업 기록 보존 확인',
  );
  await page.reload();
  await page.getByRole('button', { name: '작업 이력', exact: true }).click();
  await expect(page.locator('.work-summary')).toContainText(
    '개발 반영 결과 확인',
  );
  await page.getByText('단계별 상세 기록 · 실행 근거', { exact: true }).click();
  await expect(page.locator('.timeline-segment')).toContainText(
    'Git 병합 확인 완료',
  );
  await page.screenshot({
    path: test.info().outputPath('timeline.png'),
  });
});

test('shows readable work summaries and keeps technical details available on demand', async ({
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
    data: { title: '작업 흐름 요약 확인' },
  });
  const task = await created.json();
  const gate = await (
    await page.request.post('__test__/hold-completion', { headers })
  ).json();
  try {
    await page.request.post(`api/tasks/${task.id}/messages`, {
      headers,
      data: {
        operation_id: crypto.randomUUID(),
        text: 'Inspect this browser fixture',
      },
    });
    const populated = await page.request.post('__test__/summary-timeline', {
      headers,
      data: { task_id: task.id },
    });
    expect(populated.ok()).toBe(true);
    await page.goto(`./?task=${task.id}`);
    await page.getByRole('button', { name: '작업 이력', exact: true }).click();
    const overview = page.getByRole('region', {
      name: '한눈에 보는 작업 흐름',
      exact: true,
    });
    await expect(overview).toContainText('지금 진행 중인 작업');
    await expect(overview.locator('li')).toHaveCount(3);
    await expect(overview).toContainText('질문 답변 화면 수정');
    await expect(overview).toContainText('작업별 브랜치 연결');
    await expect(overview).not.toContainText('pnpm test');
    await expect(page.locator('.work-summary-details')).not.toHaveAttribute(
      'open',
      '',
    );
    await page
      .getByText('단계별 상세 기록 · 실행 근거', { exact: true })
      .click();
    await expect(page.locator('.timeline-segment').first()).toContainText(
      'pnpm test',
    );
    await page
      .getByText('단계별 상세 기록 · 실행 근거', { exact: true })
      .click();
    await overview
      .getByRole('heading', { name: '한눈에 보는 작업 흐름' })
      .scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath('work-summary.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .getByRole('button', { name: '작업 이력 보기', exact: true })
      .click();
    await expect(overview).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  } finally {
    await page.request.post('__test__/release-completion', {
      headers,
      data: { id: gate.id },
    });
  }
});
