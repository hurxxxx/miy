import { expect, test } from '@playwright/test';

test('preserves each conversation reading position and follows new items only from the bottom', async ({
  page,
}) => {
  await page.goto('./?view=sessions');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '세션', exact: true }),
  ).toBeVisible();
  const cookies = await page.context().cookies();
  const csrf = cookies.find(
    (cookie) => cookie.name === 'codex_console_csrf',
  )?.value;
  if (!csrf) throw new Error('Missing CSRF cookie in the browser fixture');
  const headers = {
    origin: new URL(page.url()).origin,
    'x-csrf-token': csrf,
  };
  const rows: { id: string; title: string; count: number; event: number }[] =
    [];
  for (const title of [
    '긴 대화 첫 작업',
    '긴 대화 다음 작업',
    '짧은 대화 작업',
  ]) {
    const response = await page.request.post('api/tasks', {
      headers,
      data: { title, isolate: false },
    });
    expect(response.ok()).toBe(true);
    rows.push({
      ...(await response.json()),
      count: rows.length === 2 ? 1 : 40,
      event: 100,
    });
  }
  // Keep authentication, routing and task persistence real; only the long native history
  // is synthetic so this viewport check never starts a subscription/model turn.
  for (const row of rows) {
    await page.route(`**/api/tasks/${row.id}`, async (route) => {
      const response = await route.fetch();
      const detail = await response.json();
      await route.fulfill({
        json: {
          ...detail,
          event_id: row.event,
          items: Array.from({ length: row.count }, (_, index) => ({
            id: `${row.id}-message-${index}`,
            type: 'agentMessage',
            text: `${row.title} 결과 ${index + 1}\n\n세션을 전환해도 읽고 있던 이 문단의 위치가 보존되어야 합니다.`,
          })),
        },
      });
    });
  }
  const refresh = () =>
    page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await refresh();
  const open = async (row: (typeof rows)[number]) => {
    await page
      .getByRole('list', { name: '세션', exact: true })
      .getByRole('button', { name: new RegExp(row.title) })
      .click();
    await expect(page.getByRole('heading', { name: row.title })).toBeVisible();
  };
  const messages = page.locator('.messages');
  const top = () => messages.evaluate((node) => node.scrollTop);
  const bottomGap = () =>
    messages.evaluate(
      (node) => node.scrollHeight - node.clientHeight - node.scrollTop,
    );
  const scroll = async (offset: number) => {
    await messages.evaluate(
      (node, value) => node.scrollTo({ top: value, behavior: 'instant' }),
      offset,
    );
    await expect.poll(top).toBeCloseTo(offset, 0);
    // A real scroll event must update the reading mode before navigation.
    await messages.evaluate((node) => node.dispatchEvent(new Event('scroll')));
  };
  const backToList = () =>
    page.getByRole('button', { name: '세션 목록으로' }).click();

  await open(rows[0]);
  await expect.poll(bottomGap).toBeLessThan(30);
  await scroll(420);
  await backToList();
  await open(rows[0]);
  await expect.poll(top).toBeCloseTo(420, 0);

  await backToList();
  await open(rows[2]);
  await expect.poll(top).toBeLessThan(200);
  await expect.poll(bottomGap).toBeLessThan(2);
  await backToList();
  await open(rows[0]);
  await expect.poll(top).toBeCloseTo(420, 0);

  await backToList();
  await open(rows[1]);
  await expect.poll(bottomGap).toBeLessThan(30);
  await scroll(640);
  await page.goBack();
  await expect(
    page.getByRole('heading', { name: '세션', exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole('heading', { name: rows[0].title }),
  ).toBeVisible();
  await expect.poll(top).toBeCloseTo(420, 0);
  await backToList();
  await open(rows[1]);
  await expect.poll(top).toBeCloseTo(640, 0);
  await backToList();
  await open(rows[0]);
  await expect.poll(top).toBeCloseTo(420, 0);

  rows[0].count += 3;
  rows[0].event += 1;
  await refresh();
  await expect(
    messages.getByText(`${rows[0].title} 결과 43`, { exact: true }),
  ).toHaveCount(1);
  await expect.poll(top).toBeCloseTo(420, 0);
  await messages.evaluate((node) =>
    node.scrollTo({ top: node.scrollHeight, behavior: 'instant' }),
  );
  await expect.poll(bottomGap).toBeLessThan(2);

  await messages.evaluate((node) => node.dispatchEvent(new Event('scroll')));
  rows[0].count += 3;
  rows[0].event += 1;
  await refresh();
  await expect(
    messages.getByText(`${rows[0].title} 결과 46`, { exact: true }),
  ).toHaveCount(1);
  await expect.poll(bottomGap).toBeLessThan(2);

  await page.setViewportSize({ width: 390, height: 844 });
  await scroll(540);
  await page.getByRole('button', { name: '결과물', exact: true }).click();
  await expect(messages).toBeHidden();
  await page.getByRole('button', { name: '대화', exact: true }).click();
  await expect.poll(top).toBeCloseTo(540, 0);
  await backToList();
  await open(rows[0]);
  await expect.poll(top).toBeCloseTo(540, 0);

  await page.getByRole('button', { name: '결과물', exact: true }).click();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(messages).toBeVisible();
  await expect.poll(top).toBeCloseTo(540, 0);
  await messages.evaluate((node) =>
    node.scrollTo({ top: node.scrollHeight, behavior: 'instant' }),
  );
  await expect.poll(bottomGap).toBeLessThan(2);
  await messages.evaluate((node) => node.dispatchEvent(new Event('scroll')));
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(messages).toBeHidden();
  rows[0].count += 3;
  rows[0].event += 1;
  await refresh();
  await expect(
    messages.getByText(`${rows[0].title} 결과 49`, { exact: true }),
  ).toHaveCount(1);
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(messages).toBeVisible();
  await expect.poll(bottomGap).toBeLessThan(2);
});
