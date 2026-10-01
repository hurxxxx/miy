import { expect, test } from '@playwright/test';
import type { Task } from '../src/api';

test('global activity follows parallel agents through completion across pages and mobile', async ({
  page,
}) => {
  const task: Task = {
    id: '00000000-0000-4000-8000-000000000077',
    title: '병렬 점검',
    status: 'running',
    stage: 'plan',
    thread_id: 'root',
    turn_id: 'turn',
    root: '/fixture',
    isolated: false,
    approved_revision: null,
    error_code: null,
    updated_at: new Date().toISOString(),
    permissions: 'read-only',
    pinned: false,
    pending_count: 0,
    executor: 'session',
    progress: { steps: [{ step: '변경 사항 점검 중', status: 'inProgress' }] },
    agents: [
      {
        thread_id: 'root',
        name: 'Codex',
        status: 'active',
        flags: [],
        updated_at: new Date().toISOString(),
      },
      {
        thread_id: 'child',
        parent_thread_id: 'root',
        name: '리뷰 에이전트',
        role: 'reviewer',
        status: 'active',
        flags: [],
        updated_at: new Date().toISOString(),
      },
    ],
  };
  await page.route('**/api/overview', (route) =>
    route.fulfill({ json: [task] }),
  );
  await page.goto('./?view=templates');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const trigger = page.getByRole('button', { name: /^에이전트 활동 ·/ });
  await expect(trigger).toHaveAccessibleName(/실행 중 에이전트: 2/);
  await expect(page.getByRole('dialog', { name: '에이전트 활동' })).toHaveCount(
    0,
  );
  await trigger.click();
  const panel = page.getByRole('dialog', { name: '에이전트 활동' });
  await expect(panel.getByText('변경 사항 점검 중')).toBeVisible();
  await panel.getByText('에이전트 상세', { exact: false }).click();
  await expect(panel.getByText('리뷰 에이전트', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '모니터링' })
    .click();
  await expect(trigger).toHaveAccessibleName(/실행 중 에이전트: 2/);
  await trigger.click();
  await panel.getByRole('button', { name: /병렬 점검/ }).focus();
  task.status = 'idle';
  task.agents.forEach((agent) => {
    agent.status = 'completed';
  });
  await page.evaluate(() =>
    document.dispatchEvent(new Event('visibilitychange')),
  );
  await expect(trigger).toHaveAccessibleName(
    /실행 중 에이전트: 0.*최근 종료: 1/,
  );
  await expect(
    panel.getByRole('region', { name: '최근 종료' }).getByText('병렬 점검'),
  ).toBeVisible();
  await expect(panel.getByRole('button', { name: /병렬 점검/ })).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  const box = await panel.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  await panel.getByRole('button', { name: '전체 에이전트 보기' }).click();
  await expect(page).toHaveURL(/view=agents/);
  await expect(panel).toHaveCount(0);
  await trigger.click();
  await expect(panel.getByText('병렬 점검')).toBeVisible();
  await panel.getByRole('button', { name: '에이전트 활동 닫기' }).click();
  await expect(trigger).toBeFocused();
});
