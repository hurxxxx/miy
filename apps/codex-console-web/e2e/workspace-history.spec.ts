import { expect, test } from '@playwright/test';
import { openNewTask, submitNewTask } from './task-submission';

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 390, height: 844 },
]) {
  test(`durable work history and workspace alignment at ${viewport.width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(viewport);
    await page.goto('./?view=sessions');
    await page
      .getByLabel('본인 전용 비밀번호')
      .fill('console-tests-only-password');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await openNewTask(page);
    await page
      .getByRole('dialog')
      .getByLabel('작업 이름 (선택)')
      .fill('작업 이력과 정렬 확인');
    await submitNewTask(page);
    await page
      .getByLabel('실행 모드', { exact: true })
      .selectOption('implement');
    await page.getByLabel('요청 내용 입력').fill('Add a greeting');
    const composerBefore = await page.locator('.composer').boundingBox();
    await page.getByLabel('요청 내용 입력').focus();
    expect(await page.locator('.composer').boundingBox()).toEqual(
      composerBefore,
    );
    expect(
      (await page
        .getByRole('button', { name: '설정 변경', exact: true })
        .boundingBox())!.width,
    ).toBeLessThanOrEqual(260);
    if (viewport.width > 1000)
      await page
        .locator('.composer')
        .screenshot({
          path: testInfo.outputPath('composer-' + viewport.width + '.png'),
        });
    await page.getByRole('button', { name: '보내기', exact: true }).click();
    await expect(page.locator('.execution-status-heading')).toContainText(
      '결과 확인 가능',
    );
    if (viewport.width > 1000) {
      await expect(
        page.getByRole('separator', { name: '대화와 결과 영역 크기 조절' }),
      ).toHaveAttribute('aria-valuenow', '50');
      const header = await page.locator('.task-header').boundingBox();
      expect(header!.height).toBeLessThan(135);
      const messages = await page.locator('.messages').boundingBox();
      const composer = await page.locator('.composer').boundingBox();
      expect(Math.abs(messages!.x + 20 - composer!.x)).toBeLessThan(1);
    }
    await page
      .getByRole('region', { name: '현재 실행 상태', exact: true })
      .getByRole('button', { name: '작업 이력 보기', exact: true })
      .click();
    const history = page.getByRole('region', {
      name: '작업 이력',
      exact: true,
    });
    await expect(
      history.getByText('명령 실행 종료', { exact: true }),
    ).toBeVisible();
    await expect(
      history.getByText('진행 단계 업데이트', { exact: true }),
    ).toBeVisible();
    await expect(history.getByText('실행 완료', { exact: true })).toBeVisible();
    const id = new URL(page.url()).searchParams.get('task')!;
    const before = await (
      await page.request.get('api/tasks/' + id + '/history')
    ).json();
    await page.screenshot({
      path: testInfo.outputPath('history-' + viewport.width + '.png'),
    });
    await page.reload();
    await page
      .getByRole('region', { name: '현재 실행 상태', exact: true })
      .getByRole('button', { name: '작업 이력 보기', exact: true })
      .click();
    await expect(
      history.getByText('명령 실행 종료', { exact: true }),
    ).toBeVisible();
    const after = await (
      await page.request.get('api/tasks/' + id + '/history')
    ).json();
    expect(after.items.map((row: { id: number }) => row.id)).toEqual(
      before.items.map((row: { id: number }) => row.id),
    );
    await history
      .getByRole('button', { name: '명령·파일', exact: true })
      .click();
    await expect(
      history.getByText('명령 실행 종료', { exact: true }),
    ).toBeVisible();
    await expect(
      history.getByText('진행 단계 업데이트', { exact: true }),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
