import { expect, test } from '@playwright/test';
import type { Task } from '../src/api';

const task = (index: number, status: 'waiting' | 'running'): Task => ({
  id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  title: `${status === 'waiting' ? '확인이 필요한 작업' : '진행 중인 작업'} ${String(index).padStart(2, '0')}`,
  status,
  stage: 'implement',
  executor: 'session',
  thread_id: null,
  turn_id: null,
  root: '/fixture',
  isolated: false,
  approved_revision: null,
  error_code: null,
  updated_at: '2026-10-12T09:00:00Z',
  permissions: 'ask',
  pinned: false,
  pending_count: status === 'waiting' ? 1 : 0,
  agents: [],
  context: { area: 'studio', purpose: 'development' },
  summary: {
    project_title: '운영 도구',
    pending_kinds: status === 'waiting' ? ['approval'] : [],
  },
});

for (const width of [1280, 1440, 1920]) {
  for (const withRunning of [false, true]) {
    test(`many decision cards use the content width without an inner scroll at ${width}px (running=${withRunning})`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize({
        width,
        height: width === 1920 ? 1080 : 900,
      });
      const waiting = Array.from({ length: 12 }, (_, index) =>
        task(index + 1, 'waiting'),
      );
      const running = withRunning
        ? Array.from({ length: 3 }, (_, index) => task(index + 13, 'running'))
        : [];
      await page.route('**/api/overview', (route) =>
        route.fulfill({ json: [...waiting, ...running] }),
      );
      await page.goto('./?view=studio');
      await page
        .getByLabel('본인 전용 비밀번호')
        .fill('console-tests-only-password');
      await page.getByRole('button', { name: '로그인', exact: true }).click();
      const decisions = page.getByRole('region', {
        name: '내 확인이 필요한 작업',
        exact: true,
      });
      const cards = decisions.locator('.work-preview');
      await expect(cards).toHaveCount(12);
      const library = await page
        .getByRole('region', { name: '앱과 프로젝트 목록' })
        .boundingBox();
      const section = await decisions.boundingBox();
      const first = await cards.first().boundingBox();
      const second = await cards.nth(1).boundingBox();
      expect(Math.abs(section!.width - library!.width)).toBeLessThan(1);
      expect(second!.x).toBeGreaterThanOrEqual(first!.x + first!.width);
      expect(Math.abs(second!.y - first!.y)).toBeLessThan(1);
      for (const queue of await page
        .locator('.studio-activity .work-queue')
        .all()) {
        const geometry = await queue.evaluate((element) => ({
          height: element.clientHeight,
          contentHeight: element.scrollHeight,
        }));
        expect(geometry.contentHeight).toBeLessThanOrEqual(geometry.height + 1);
      }
      if (withRunning) {
        const progress = await page
          .getByRole('region', { name: '진행 중인 작업', exact: true })
          .boundingBox();
        expect(progress!.y).toBeGreaterThanOrEqual(
          section!.y + section!.height,
        );
        expect(Math.abs(progress!.width - section!.width)).toBeLessThan(1);
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`cards-top-${width}-${withRunning}.png`),
      });
      await cards.last().scrollIntoViewIfNeeded();
      await expect(cards.last()).toBeInViewport();
      expect(
        await decisions
          .locator('.work-queue')
          .evaluate((element) => element.scrollTop),
      ).toBe(0);
      await page.screenshot({
        path: testInfo.outputPath(`cards-bottom-${width}-${withRunning}.png`),
      });
    });
  }
}
