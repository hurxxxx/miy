import { expect, test } from '@playwright/test';
import type { components } from '@miy/contracts/openapi.generated';
import {
  stubAppDataBackend,
  stubConversationsApi,
  stubShellBackend,
} from './helpers';

// Synthetic data and intercepted transport only: this suite never sends mail.
const account: components['schemas']['MailAccountOut'] = {
  id: 'test-mail-account',
  email_address: 'owner@example.test',
  display_name: 'Test owner',
  account_label: 'Synthetic inbox',
  protocol: 'imap',
  provider_kind: 'custom',
  incoming_host: 'imap.example.test',
  incoming_port: 993,
  incoming_security: 'ssl',
  incoming_username: 'owner@example.test',
  smtp_host: 'smtp.example.test',
  smtp_port: 465,
  smtp_security: 'ssl',
  smtp_username: 'owner@example.test',
  sync_enabled: true,
  status: 'connected',
  last_sync_at: null,
  last_error: null,
  last_sync_new_count: 0,
  last_sync_updated_count: 0,
  last_sync_deleted_count: 0,
  created_at: '2026-10-06T09:00:00Z',
  updated_at: '2026-10-06T09:00:00Z',
};

const message: components['schemas']['MailMessageDetail'] = {
  id: 'test-message',
  account_id: account.id,
  folder: 'INBOX',
  subject: 'Synthetic release review',
  from_text: 'Reviewer <reviewer@example.test>',
  to_text: account.email_address,
  cc_text: '',
  snippet: 'Review the release checklist.',
  received_at: '2026-10-06T10:00:00Z',
  is_read: true,
  is_starred: false,
  has_attachments: false,
  body: {
    text_body: 'Review the release checklist.',
    html_body: `<p>Review the release checklist.</p>
      <script>window.parent.mailScriptExecuted = true</script>
      <form action="https://mail-body.test/forbidden"><input name="secret"></form>
      <a href="https://mail-body.test/review">Review link</a>
      <img src="https://mail-body.test/illustration.svg" alt="Synthetic illustration"
        onerror="window.parent.mailScriptExecuted = true">`,
  },
  attachments: [],
};

type MailDraft = components['schemas']['MailDraftOut'];

function makeDraft(): MailDraft {
  return {
    id: 'test-draft',
    account_id: account.id,
    source_message_id: message.id,
    to_text: 'reviewer@example.test',
    cc_text: '',
    bcc_text: '',
    subject: 'Re: Synthetic release review',
    text_body: 'I will review the checklist.',
    html_body: '',
    ai_generated: true,
    status: 'draft',
    send_error: null,
    sent_message_id: null,
    sent_at: null,
    created_at: '2026-10-06T10:30:00Z',
    updated_at: '2026-10-06T10:30:00Z',
  };
}

test('Mail preserves its admitted inbox, HTML boundary and save-before-send flow', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page);
  await stubConversationsApi(page);
  const errors: string[] = [];
  const actions: string[] = [];
  const imageReferrers: string[] = [];
  let draft: MailDraft | null = null;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('https://mail-body.test/**', (route) => {
    expect(new URL(route.request().url()).pathname).toBe('/illustration.svg');
    imageReferrers.push(route.request().headers()['referer'] ?? '');
    return route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
    });
  });
  await page.route('**/api/v1/mail/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice('/api/v1/mail'.length);
    const method = request.method();
    if (method === 'GET' && path === '/accounts')
      return route.fulfill({ json: [account] });
    if (method === 'GET' && path === '/messages')
      return route.fulfill({ json: { items: [message], total: 1 } });
    if (method === 'GET' && path === `/messages/${message.id}`)
      return route.fulfill({ json: message });
    if (method === 'GET' && path === '/drafts')
      return route.fulfill({ json: draft ? [draft] : [] });
    if (method === 'POST' && path === `/messages/${message.id}/summarize`) {
      actions.push('summary');
      return route.fulfill({
        json: {
          message_id: message.id,
          summary: 'Synthetic checklist summary',
        },
      });
    }
    if (method === 'POST' && path === `/messages/${message.id}/reply-draft`) {
      expect(request.postDataJSON()).toEqual({
        instruction: 'Confirm the review.',
      });
      actions.push('reply');
      draft = makeDraft();
      return route.fulfill({ json: draft });
    }
    if (method === 'PATCH' && path === '/drafts/test-draft' && draft) {
      expect(request.postDataJSON().text_body).toBe('Reviewed the checklist.');
      actions.push('save');
      draft = { ...draft, ...request.postDataJSON() };
      return route.fulfill({ json: draft });
    }
    if (method === 'POST' && path === '/drafts/test-draft/send' && draft) {
      expect(actions.at(-1)).toBe('save');
      actions.push('send');
      draft = { ...draft, status: 'sent', sent_at: '2026-10-06T11:00:00Z' };
      return route.fulfill({ json: draft });
    }
    errors.push(`Unexpected synthetic mail request: ${method} ${path}`);
    return route.fulfill({
      status: 500,
      json: { detail: 'Unexpected fixture request' },
    });
  });

  await page.goto('/apps/mail');
  await expect(
    page.getByRole('heading', { level: 1, name: '메일', exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: /Reviewer.*Synthetic release review/ })
    .click();
  await expect(
    page.getByRole('heading', { level: 2, name: message.subject }),
  ).toBeVisible();
  const iframe = page.getByTitle('메일 HTML 본문', { exact: true });
  await expect(iframe).toHaveAttribute(
    'sandbox',
    'allow-popups allow-popups-to-escape-sandbox',
  );
  await expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer');
  const body = page.frameLocator('iframe[title="메일 HTML 본문"]');
  await expect(
    body.getByText('Review the release checklist.', { exact: true }),
  ).toBeVisible();
  await expect(body.locator('script, form, input, [onerror]')).toHaveCount(0);
  await expect(body.getByRole('link', { name: 'Review link' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  );
  await expect.poll(() => imageReferrers.length).toBeGreaterThan(0);
  expect(imageReferrers.every((value) => value === '')).toBe(true);
  expect(
    await page.evaluate(() => Reflect.has(window, 'mailScriptExecuted')),
  ).toBe(false);

  await page.getByRole('button', { name: '요약', exact: true }).click();
  await expect(
    page.getByText('Synthetic checklist summary', { exact: true }),
  ).toBeVisible();
  await page
    .getByRole('textbox', { name: '답장 방향이나 포함할 내용을 입력하세요.' })
    .fill('Confirm the review.');
  await page.getByRole('button', { name: '답장 초안', exact: true }).click();
  await expect.poll(() => actions).toEqual(['summary', 'reply']);
  await page.goto('/apps/mail?view=drafts');
  await page
    .getByRole('button', { name: /Re: Synthetic release review/ })
    .click();
  await page
    .getByRole('textbox', { name: '메일 HTML 본문', exact: true })
    .fill('Reviewed the checklist.');
  const send = page.getByRole('button', { name: '발송', exact: true });
  await send.click();
  await expect(send).toBeDisabled();
  await expect
    .poll(() => actions)
    .toEqual(['summary', 'reply', 'save', 'send']);
  expect(errors).toEqual([]);
});

test('Mail admission denies the moved business view before any mail data request', async ({
  page,
}) => {
  await stubAppDataBackend(page);
  await stubShellBackend(page, { enabledAppIds: ['home'] });
  await stubConversationsApi(page);
  const requests: string[] = [];
  await page.route('**/api/v1/mail/**', (route) => {
    requests.push(route.request().url());
    return route.fulfill({ status: 403, json: { detail: 'denied' } });
  });
  await page.goto('/apps/mail?view=drafts');
  await expect(
    page.getByRole('heading', { name: '접근 권한 없음' }),
  ).toBeVisible();
  expect(requests).toEqual([]);
});
