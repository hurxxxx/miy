import { expect, test } from '@playwright/test';

test('edits a template, runs independent sessions, and retains history after editing', async ({
  page,
}) => {
  await page.goto('./?view=templates');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await page.getByRole('button', { name: '템플릿 만들기' }).click();
  const editor = page.getByRole('dialog');
  const name = `검증 템플릿 ${Date.now()}`;
  await editor.getByLabel('템플릿 이름').fill(name);
  await editor
    .getByLabel('프롬프트', { exact: true })
    .fill('Explain {{topic}}');
  await editor.getByLabel('실행 모드').selectOption('plan');
  await editor.getByRole('button', { name: '입력값 추가' }).click();
  await editor.getByLabel('입력값 이름', { exact: true }).fill('topic');
  await editor.getByLabel('화면에 표시할 이름').fill('질문할 내용');
  await editor.getByRole('button', { name: '템플릿 저장' }).click();
  await expect(editor).not.toBeVisible();
  const row = page
    .locator('.template-row')
    .filter({ has: page.getByRole('heading', { name, exact: true }) });
  await page.getByLabel('템플릿 검색', { exact: true }).fill(name);
  await expect(page.locator('.template-row')).toHaveCount(1);
  await page
    .getByLabel('템플릿 검색', { exact: true })
    .fill(`${name} 없는 항목`);
  await expect(
    page.getByRole('heading', { name: '검색한 템플릿이 없습니다' }),
  ).toBeVisible();
  await page.getByRole('button', { name: '필터 초기화' }).click();
  await expect(row).toBeVisible();
  const more = row.getByRole('button', { name: '템플릿 더보기' });
  await more.focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('menuitem', { name: '편집', exact: true }),
  ).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(more).toBeFocused();
  await row.getByRole('button', { name: '실행', exact: true }).click();
  await page
    .getByRole('dialog')
    .getByLabel('질문할 내용')
    .fill('the repository');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: '실행', exact: true })
    .click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(page).toHaveURL(/task=[0-9a-f-]+/);
  const first = new URL(page.url()).searchParams.get('task');
  await expect(page.getByLabel('현재 실행 상태')).toContainText('준비됨');
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿' })
    .click();
  await row.getByRole('button', { name: '템플릿 더보기' }).click();
  await page.getByRole('menuitem', { name: '편집', exact: true }).click();
  const renamed = `${name} 변경`;
  await editor.getByLabel('템플릿 이름').fill(renamed);
  await editor
    .getByLabel('프롬프트', { exact: true })
    .fill('Summarize {{topic}}');
  await editor.getByLabel('기본값').fill('the project');
  await editor.getByRole('button', { name: '템플릿 저장' }).click();
  const updatedRow = page
    .locator('.template-row')
    .filter({ has: page.getByRole('heading', { name: renamed, exact: true }) });
  await updatedRow.getByRole('button', { name: '실행', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: renamed, exact: true }),
  ).toBeVisible();
  await expect
    .poll(() => new URL(page.url()).searchParams.get('task'))
    .not.toBe(first);
  await expect(page).toHaveURL(/task=[0-9a-f-]+/);
  await expect(page.getByLabel('현재 실행 상태')).toContainText('준비됨');
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿', exact: true })
    .click();
  await updatedRow
    .getByRole('button', { name: '실행 이력', exact: true })
    .click();
  await expect(page).toHaveURL(/view=agents&template=[0-9a-f-]+/);
  const historyUrl = page.url();
  await expect(
    page.getByRole('region', { name: '선택한 템플릿' }),
  ).toContainText(renamed);
  const runs = page.locator('.agent-run');
  await expect(runs).toHaveCount(2);
  await runs.nth(1).getByText('실행 당시 설정', { exact: true }).click();
  await runs.nth(1).getByText('실행한 요청', { exact: true }).click();
  await expect(runs.nth(1)).toContainText('Explain the repository');
  await page.reload();
  await expect(runs).toHaveCount(2);
  await runs.nth(1).getByRole('button', { name: '대화·결과 열기' }).click();
  await expect(page).toHaveURL(new RegExp(`task=${first}`));
  await page.goBack();
  await expect(page).toHaveURL(historyUrl);
  await expect(runs).toHaveCount(2);
  await page
    .getByRole('group', { name: '상태 필터' })
    .getByRole('button', { name: /^종료/ })
    .click();
  await expect(runs).toHaveCount(2);
  await page.getByLabel('작업 검색', { exact: true }).fill(renamed);
  await expect(runs).toHaveCount(1);
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿', exact: true })
    .click();
  await updatedRow.getByRole('button', { name: '템플릿 더보기' }).click();
  await page.getByRole('menuitem', { name: '복제', exact: true }).click();
  const copiedName = `${name} 복제본`;
  await editor.getByLabel('템플릿 이름').fill(copiedName);
  await editor.getByRole('button', { name: '템플릿 저장' }).click();
  const copiedRow = page.locator('.template-row').filter({
    has: page.getByRole('heading', { name: copiedName, exact: true }),
  });
  await copiedRow
    .getByRole('button', { name: '실행 이력', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: '아직 실행 이력이 없습니다' }),
  ).toBeVisible();
  await expect(runs).toHaveCount(0);
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿', exact: true })
    .click();
  await updatedRow.getByRole('button', { name: '템플릿 더보기' }).click();
  await page
    .getByRole('menuitem', { name: '템플릿 보관', exact: true })
    .click();
  await page.getByLabel('보관한 템플릿 표시').check();
  await updatedRow
    .getByRole('button', { name: '실행 이력', exact: true })
    .click();
  await expect(page).toHaveURL(historyUrl);
  await expect(
    page.getByRole('region', { name: '선택한 템플릿' }),
  ).toContainText('보관된 템플릿');
  await expect(runs).toHaveCount(2);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole('button', { name: '전체 에이전트 보기', exact: true })
    .click();
  await expect(page).toHaveURL(/\?view=agents$/);
  await expect(
    page.getByRole('heading', { name: '에이전트', exact: true }),
  ).toBeVisible();
});

test('monitoring navigation works on a narrow screen without horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('./?view=monitoring');
  await page
    .getByLabel('본인 전용 비밀번호')
    .fill('console-tests-only-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '서버 자원' })).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Codex 호환성' }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: '메뉴 열기' }).click();
  await page
    .getByRole('navigation', { name: '콘솔 메뉴' })
    .getByRole('button', { name: '작업 템플릿' })
    .click();
  await expect(
    page.getByRole('heading', { name: '작업 템플릿' }),
  ).toBeVisible();
  await expect(page.locator('.sidebar.open')).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole('heading', { name: '서버 자원' })).toBeVisible();
});
