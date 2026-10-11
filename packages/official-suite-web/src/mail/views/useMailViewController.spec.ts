import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { createElement, StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  MailAccount,
  MailAccountConnectionPayload,
  MailDraft,
  MailMessage,
  MailMessageDetail,
} from '../api/mail-api';
import {
  useMailViewController,
  type MailViewControllerMessages,
  type MailAdapter,
} from './useMailViewController';
import { blankAccount } from './mail-view-model';

function account(overrides: Partial<MailAccount> = {}): MailAccount {
  return {
    id: 'account-1',
    email_address: 'ada@example.com',
    display_name: 'Ada',
    account_label: 'Ada work',
    protocol: 'imap',
    provider_kind: 'custom',
    incoming_host: 'imap.example.com',
    incoming_port: 993,
    incoming_security: 'ssl',
    incoming_username: 'ada@example.com',
    smtp_host: 'smtp.example.com',
    smtp_port: 587,
    smtp_security: 'starttls',
    smtp_username: 'ada@example.com',
    sync_enabled: true,
    status: 'active',
    last_sync_at: null,
    last_error: null,
    last_sync_new_count: 0,
    last_sync_updated_count: 0,
    last_sync_deleted_count: 0,
    ...overrides,
  };
}

function message(overrides: Partial<MailMessage> = {}): MailMessage {
  return {
    id: 'message-1',
    account_id: 'account-1',
    folder: 'inbox',
    subject: 'Subject',
    from_text: 'Ada <ada@example.com>',
    to_text: 'team@example.com',
    cc_text: '',
    snippet: 'Hello',
    received_at: '2026-05-30T00:00:00Z',
    is_read: true,
    is_starred: false,
    has_attachments: false,
    ...overrides,
  };
}

function detail(overrides: Partial<MailMessageDetail> = {}): MailMessageDetail {
  return {
    ...message(overrides),
    body: { text_body: 'Hello', html_body: '<p>Hello</p>' },
    attachments: [],
    ...overrides,
  };
}

function draft(overrides: Partial<MailDraft> = {}): MailDraft {
  return {
    id: 'draft-1',
    account_id: 'account-1',
    source_message_id: null,
    to_text: 'team@example.com',
    cc_text: '',
    bcc_text: '',
    subject: 'Draft',
    text_body: 'Draft body',
    html_body: '',
    ai_generated: false,
    status: 'draft',
    send_error: null,
    sent_message_id: null,
    sent_at: null,
    ...overrides,
  };
}

function payload(
  overrides: Partial<MailAccountConnectionPayload> = {},
): MailAccountConnectionPayload {
  return {
    ...blankAccount(),
    email_address: 'ada@example.com',
    incoming_host: 'imap.example.com',
    incoming_username: 'ada@example.com',
    incoming_password: 'secret',
    smtp_host: 'smtp.example.com',
    ...overrides,
  };
}

function messages(): MailViewControllerMessages {
  return {
    loadFailed: 'load failed',
    messageLoadFailed: 'message load failed',
    accountCreateFailed: 'account create failed',
    accountUpdateFailed: 'account update failed',
    syncFailed: 'sync failed',
    aiFailed: 'ai failed',
    sendFailed: 'send failed',
    accountConnected: 'account connected',
    accountUpdated: 'account updated',
    syncQueued: 'sync queued',
    draftCreated: 'draft created',
    draftSent: 'draft sent',
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

function adapter(overrides: Partial<MailAdapter> = {}): MailAdapter {
  return {
    listAccounts: vi.fn().mockResolvedValue([account()]),
    listMessages: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listDrafts: vi.fn().mockResolvedValue([]),
    getMessage: vi.fn().mockResolvedValue(detail()),
    updateFlags: vi.fn().mockResolvedValue(message()),
    testAccount: vi.fn().mockResolvedValue({
      incoming_ok: true,
      smtp_ok: true,
      incoming_error: null,
      smtp_error: null,
    }),
    createAccount: vi.fn().mockResolvedValue(account()),
    updateAccount: vi.fn().mockResolvedValue(account()),
    syncAccount: vi
      .fn()
      .mockResolvedValue({ account: account(), queued: true, job_id: 'job-1' }),
    summarizeMessage: vi
      .fn()
      .mockResolvedValue({ message_id: 'message-1', summary: 'Summary' }),
    createReplyDraft: vi.fn().mockResolvedValue(draft()),
    updateDraft: vi.fn().mockResolvedValue(draft()),
    sendDraft: vi.fn().mockResolvedValue(draft({ status: 'sent' })),
    ...overrides,
  };
}

function renderController(
  options: {
    client?: MailAdapter;
    view?: 'messages' | 'drafts' | 'settings';
    unread?: boolean;
    starred?: boolean;
    strict?: boolean;
  } = {},
) {
  const notify = { success: vi.fn() };
  const client = options.client ?? adapter();
  const initialProps: {
    token: string;
    view?: 'messages' | 'drafts' | 'settings';
    unread?: boolean;
    starred?: boolean;
  } = { token: 'token-1' };
  const rendered = renderHook(
    ({
      token,
      view = options.view ?? 'messages',
      unread = options.unread ?? false,
      starred = options.starred ?? false,
    }) =>
      useMailViewController({
        token,
        view,
        unread,
        starred,
        messages: messages(),
        notify,
        client,
      }),
    {
      initialProps,
      wrapper: options.strict
        ? ({ children }) => createElement(StrictMode, null, children)
        : undefined,
    },
  );
  return { ...rendered, client, notify };
}

afterEach(cleanup);

describe('useMailViewController', () => {
  it('loads a usable current session after StrictMode effect replay', async () => {
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({ items: [message()], total: 1 }),
    });
    const { result } = renderController({ client, strict: true });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    await act(async () => result.current.actions.summarizeMessage());
    expect(result.current.state.summary).toBe('Summary');
  });

  it('reloads the selected detail on return after abandoning its earlier pending read', async () => {
    const first = deferred<MailMessageDetail>();
    const client = adapter({
      listMessages: vi
        .fn()
        .mockResolvedValue({ items: [message({ is_read: false })], total: 1 }),
      getMessage: vi
        .fn()
        .mockImplementationOnce(() => first.promise)
        .mockResolvedValue(detail({ is_read: true })),
    });
    const { result, rerender } = renderController({ client });
    await waitFor(() => expect(client.getMessage).toHaveBeenCalledTimes(1));
    rerender({ token: 'token-1', view: 'settings' });
    await act(async () => first.resolve(detail({ is_read: false })));
    expect(client.updateFlags).not.toHaveBeenCalled();
    expect(result.current.state.detail).toBeNull();
    rerender({ token: 'token-1', view: 'messages' });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    expect(client.getMessage).toHaveBeenCalledTimes(2);
  });

  it('does not mark a late detail read after leaving its message view', async () => {
    const pending = deferred<MailMessageDetail>();
    const client = adapter({
      listMessages: vi
        .fn()
        .mockResolvedValue({ items: [message({ is_read: false })], total: 1 }),
      getMessage: vi.fn(() => pending.promise),
    });
    const { result, rerender } = renderController({ client });
    await waitFor(() => expect(client.getMessage).toHaveBeenCalledTimes(1));
    rerender({ token: 'token-1', view: 'settings' });
    await act(async () => pending.resolve(detail({ is_read: false })));
    expect(client.updateFlags).not.toHaveBeenCalled();
    expect(result.current.state.detail).toBeNull();
  });

  it('does not create an account after leaving settings while its test is pending', async () => {
    const tested = deferred<Awaited<ReturnType<MailAdapter['testAccount']>>>();
    const client = adapter({ testAccount: vi.fn(() => tested.promise) });
    const { result, rerender, notify } = renderController({
      client,
      view: 'settings',
    });
    await waitFor(() => expect(result.current.state.accounts).toHaveLength(1));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.actions.createAccount();
    });
    rerender({ token: 'token-1', view: 'messages' });
    await act(async () => {
      tested.resolve({
        incoming_ok: true,
        smtp_ok: true,
        incoming_error: null,
        smtp_error: null,
      });
      await pending;
    });
    expect(client.createAccount).not.toHaveBeenCalled();
    expect(notify.success).not.toHaveBeenCalled();
    expect(result.current.state.busy).toBe(false);
  });

  it('does not reload an earlier filter after a submitted sync completes', async () => {
    const synced = deferred<Awaited<ReturnType<MailAdapter['syncAccount']>>>();
    const client = adapter({
      syncAccount: vi.fn(() => synced.promise),
      listMessages: vi.fn(async (_token, params) => ({
        items: [message({ subject: params.unread ? 'Unread' : 'All' })],
        total: 1,
      })),
    });
    const { result, rerender } = renderController({ client });
    await waitFor(() =>
      expect(result.current.state.messages[0]?.subject).toBe('All'),
    );
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.actions.syncAccount('account-1');
    });
    rerender({ token: 'token-1', unread: true });
    await waitFor(() =>
      expect(result.current.state.messages[0]?.subject).toBe('Unread'),
    );
    await act(async () => {
      synced.resolve({ account: account(), queued: true, job_id: 'job-1' });
      await pending;
    });
    expect(result.current.state.messages[0]?.subject).toBe('Unread');
    expect(client.listMessages).toHaveBeenCalledTimes(2);
  });

  it.each(['success', 'failure'] as const)(
    'ignores an older query %s after a newer snapshot',
    async (outcome) => {
      const pending = deferred<{ items: MailMessage[]; total: number }>();
      const client = adapter({
        listMessages: vi.fn(async (_token, params) =>
          params.query === 'old'
            ? await pending.promise
            : {
                items: [message({ subject: params.query || 'initial' })],
                total: 1,
              },
        ),
      });
      const { result } = renderController({ client });
      await waitFor(() =>
        expect(result.current.state.messages).toHaveLength(1),
      );
      let oldRequest!: Promise<void>;
      act(() => {
        oldRequest = result.current.actions.refresh('old');
      });
      await act(async () => result.current.actions.refresh('latest'));
      await act(async () => {
        if (outcome === 'success')
          pending.resolve({ items: [message({ subject: 'old' })], total: 1 });
        else pending.reject(new Error('obsolete list error'));
        await oldRequest;
      });
      expect(result.current.state.messages[0]?.subject).toBe('latest');
      expect(result.current.state.error).toBeNull();
    },
  );

  it('does not create an account after its connection test outlives the login', async () => {
    const tested = deferred<Awaited<ReturnType<MailAdapter['testAccount']>>>();
    const client = adapter({ testAccount: vi.fn(() => tested.promise) });
    const { result, rerender, notify } = renderController({
      client,
      view: 'settings',
    });
    await waitFor(() => expect(result.current.state.accounts).toHaveLength(1));
    act(() => result.current.actions.setAccountForm(payload()));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.actions.createAccount();
    });
    rerender({ token: 'token-2' });
    await act(async () => {
      tested.resolve({
        incoming_ok: true,
        smtp_ok: true,
        incoming_error: null,
        smtp_error: null,
      });
      await pending;
    });
    expect(client.createAccount).not.toHaveBeenCalled();
    expect(notify.success).not.toHaveBeenCalled();
    expect(result.current.state.accountForm.incoming_password).toBe('');
    expect(result.current.state.error).toBeNull();
  });

  it('does not send a saved draft after the view unmounts', async () => {
    const saved = deferred<MailDraft>();
    const client = adapter({
      listDrafts: vi.fn().mockResolvedValue([draft()]),
      updateDraft: vi.fn(() => saved.promise),
    });
    const { result, unmount, notify } = renderController({
      client,
      view: 'drafts',
    });
    await waitFor(() => expect(result.current.selectedDraft).not.toBeNull());
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.actions.sendDraft(result.current.selectedDraft);
    });
    unmount();
    await act(async () => {
      saved.resolve(draft());
      await pending;
    });
    expect(client.sendDraft).not.toHaveBeenCalled();
    expect(notify.success).not.toHaveBeenCalled();
  });

  it('does not revive a summary when selecting away and back to the same message', async () => {
    const pending = deferred<{ message_id: string; summary: string }>();
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({
        items: [message(), message({ id: 'message-2' })],
        total: 2,
      }),
      getMessage: vi.fn(async (_token, id) => detail({ id })),
      summarizeMessage: vi.fn(() => pending.promise),
    });
    const { result } = renderController({ client });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    let action!: Promise<void>;
    act(() => {
      action = result.current.actions.summarizeMessage();
    });
    act(() => result.current.actions.selectMessage('message-2'));
    act(() => result.current.actions.selectMessage('message-1'));
    await act(async () => {
      pending.resolve({ message_id: 'message-1', summary: 'Obsolete summary' });
      await action;
    });
    expect(result.current.state.summary).toBe('');
  });

  it('keeps the previous detail unavailable while loading the selected message', async () => {
    const second = deferred<MailMessageDetail>();
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({
        items: [message(), message({ id: 'message-2' })],
        total: 2,
      }),
      getMessage: vi.fn(async (_token, id) =>
        id === 'message-1' ? detail() : await second.promise,
      ),
    });
    const { result } = renderController({ client });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    act(() => result.current.actions.selectMessage('message-2'));
    expect(result.current.state.detail).toBeNull();
    await act(async () => {
      await result.current.actions.summarizeMessage();
      await result.current.actions.createReplyDraft();
    });
    expect(client.summarizeMessage).not.toHaveBeenCalled();
    expect(client.createReplyDraft).not.toHaveBeenCalled();
    await act(async () => second.resolve(detail({ id: 'message-2' })));
  });

  it('does not mark an unread old detail after its session ends', async () => {
    const pending = deferred<MailMessageDetail>();
    const client = adapter({
      listMessages: vi.fn(async (token) => ({
        items: token === 'token-1' ? [message({ is_read: false })] : [],
        total: 0,
      })),
      getMessage: vi.fn(() => pending.promise),
    });
    const { rerender } = renderController({ client });
    await waitFor(() => expect(client.getMessage).toHaveBeenCalled());
    rerender({ token: 'token-2' });
    await act(async () => pending.resolve(detail({ is_read: false })));
    expect(client.updateFlags).not.toHaveBeenCalled();
  });

  it('does not replace the new session snapshot with a late old list', async () => {
    const oldList = deferred<{ items: MailMessage[]; total: number }>();
    const client = adapter({
      listMessages: vi.fn(async (token) =>
        token === 'token-1'
          ? await oldList.promise
          : { items: [message({ id: 'new-message' })], total: 1 },
      ),
    });
    const { result, rerender } = renderController({ client });
    rerender({ token: 'token-2' });
    await waitFor(() =>
      expect(result.current.state.messages[0]?.id).toBe('new-message'),
    );
    await act(async () =>
      oldList.resolve({ items: [message({ id: 'old-message' })], total: 1 }),
    );
    expect(result.current.state.messages[0]?.id).toBe('new-message');
  });

  it('does not apply an earlier message summary after selecting another message', async () => {
    const pendingSummary = deferred<{ message_id: string; summary: string }>();
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({
        items: [message(), message({ id: 'message-2' })],
        total: 2,
      }),
      getMessage: vi.fn(async (_token, id) => detail({ id })),
      summarizeMessage: vi.fn(() => pendingSummary.promise),
    });
    const { result } = renderController({ client });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    let action!: Promise<void>;
    act(() => {
      action = result.current.actions.summarizeMessage();
    });
    act(() => result.current.actions.selectMessage('message-2'));
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-2'),
    );
    await act(async () => {
      pendingSummary.resolve({
        message_id: 'message-1',
        summary: 'Old summary',
      });
      await action;
    });
    expect(result.current.state.summary).toBe('');
  });

  it('does not insert an old reply draft or notify the next session', async () => {
    const pendingDraft = deferred<MailDraft>();
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({ items: [message()], total: 1 }),
      createReplyDraft: vi.fn(() => pendingDraft.promise),
    });
    const { result, rerender, notify } = renderController({ client });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-1'),
    );
    let action!: Promise<void>;
    act(() => {
      action = result.current.actions.createReplyDraft();
    });
    rerender({ token: 'token-2' });
    await act(async () => {
      pendingDraft.resolve(draft({ id: 'old-draft' }));
      await action;
    });
    expect(
      result.current.state.drafts.some((item) => item.id === 'old-draft'),
    ).toBe(false);
    expect(notify.success).not.toHaveBeenCalled();
  });

  it.each(['session', 'draft'] as const)(
    'does not issue send after %s changes while saving',
    async (change) => {
      const pendingSave = deferred<MailDraft>();
      const client = adapter({
        listDrafts: vi
          .fn()
          .mockResolvedValue([draft(), draft({ id: 'draft-2' })]),
        updateDraft: vi.fn(() => pendingSave.promise),
      });
      const { result, rerender, notify } = renderController({
        client,
        view: 'drafts',
      });
      await waitFor(() =>
        expect(result.current.selectedDraft?.id).toBe('draft-1'),
      );
      let action!: Promise<void>;
      act(() => {
        action = result.current.actions.sendDraft(result.current.selectedDraft);
      });
      if (change === 'session') rerender({ token: 'token-2' });
      else act(() => result.current.actions.selectDraft('draft-2'));
      await act(async () => {
        pendingSave.resolve(draft());
        await action;
      });
      expect(client.sendDraft).not.toHaveBeenCalled();
      expect(notify.success).not.toHaveBeenCalled();
    },
  );

  it('does not replay or announce an already submitted send in the next session', async () => {
    const pendingSend = deferred<MailDraft>();
    const client = adapter({
      listDrafts: vi.fn().mockResolvedValue([draft()]),
      sendDraft: vi.fn(() => pendingSend.promise),
    });
    const { result, rerender, notify } = renderController({
      client,
      view: 'drafts',
    });
    await waitFor(() =>
      expect(result.current.selectedDraft?.id).toBe('draft-1'),
    );
    let action!: Promise<void>;
    act(() => {
      action = result.current.actions.sendDraft(result.current.selectedDraft);
    });
    await waitFor(() => expect(client.sendDraft).toHaveBeenCalledTimes(1));
    rerender({ token: 'token-2' });
    await act(async () => {
      pendingSend.resolve(draft({ status: 'sent' }));
      await action;
    });
    expect(client.sendDraft).toHaveBeenCalledTimes(1);
    expect(notify.success).not.toHaveBeenCalled();
  });

  it('loads mail snapshots with trimmed message query and filters', async () => {
    const client = adapter();
    const { result } = renderController({
      client,
      starred: true,
      unread: true,
    });

    await waitFor(() => expect(client.listMessages).toHaveBeenCalledTimes(1));
    vi.mocked(client.listMessages).mockClear();

    act(() => {
      result.current.actions.setQuery('  spec  ');
    });
    await act(async () => {
      await result.current.actions.refresh('  spec  ');
    });

    expect(client.listMessages).toHaveBeenCalledWith('token-1', {
      query: 'spec',
      unread: true,
      starred: true,
      limit: 75,
    });
  });

  it('marks unread message details as read optimistically and rolls back on flag failure', async () => {
    const unreadMessage = message({ id: 'message-1', is_read: false });
    const client = adapter({
      listMessages: vi
        .fn()
        .mockResolvedValue({ items: [unreadMessage], total: 1 }),
      getMessage: vi
        .fn()
        .mockResolvedValue(detail({ id: 'message-1', is_read: false })),
      updateFlags: vi.fn().mockRejectedValue(new Error('flag failed')),
    });
    const { result } = renderController({ client });

    await waitFor(() => {
      expect(client.updateFlags).toHaveBeenCalledWith('token-1', 'message-1', {
        is_read: true,
      });
    });
    await waitFor(() => {
      expect(result.current.state.detail?.is_read).toBe(false);
      expect(result.current.state.messages[0]?.is_read).toBe(false);
    });
  });

  it('blocks account creation when the connection test fails', async () => {
    const client = adapter({
      testAccount: vi.fn().mockResolvedValue({
        incoming_ok: false,
        smtp_ok: false,
        incoming_error: 'incoming failed',
        smtp_error: 'smtp failed',
      }),
    });
    const { result } = renderController({ client, view: 'settings' });

    act(() => {
      result.current.actions.setAccountForm(payload());
    });
    await act(async () => {
      await result.current.actions.createAccount();
    });

    expect(client.createAccount).not.toHaveBeenCalled();
    expect(result.current.state.error).toBe('incoming failed / smtp failed');
    expect(result.current.state.busy).toBe(false);
  });

  it('updates draft fields before sending and stores the sent draft', async () => {
    const initialDraft = draft({ id: 'draft-1', subject: 'Draft subject' });
    const savedDraft = draft({ id: 'draft-1', subject: 'Edited subject' });
    const sentDraft = draft({
      id: 'draft-1',
      status: 'sent',
      subject: 'Edited subject',
    });
    const client = adapter({
      listDrafts: vi.fn().mockResolvedValue([initialDraft]),
      updateDraft: vi.fn().mockResolvedValue(savedDraft),
      sendDraft: vi.fn().mockResolvedValue(sentDraft),
    });
    const { result } = renderController({ client, view: 'drafts' });

    await waitFor(() =>
      expect(result.current.selectedDraft?.id).toBe('draft-1'),
    );
    await act(async () => {
      await result.current.actions.sendDraft({
        ...initialDraft,
        subject: 'Edited subject',
      });
    });

    expect(client.updateDraft).toHaveBeenCalledWith(
      'token-1',
      'draft-1',
      expect.objectContaining({ subject: 'Edited subject' }),
    );
    expect(client.sendDraft).toHaveBeenCalledWith('token-1', 'draft-1');
    expect(
      vi.mocked(client.updateDraft).mock.invocationCallOrder[0],
    ).toBeLessThan(vi.mocked(client.sendDraft).mock.invocationCallOrder[0]);
    expect(result.current.state.drafts[0]).toEqual(sentDraft);
  });

  it('ignores stale message detail responses after selection changes', async () => {
    const firstDetail = deferred<MailMessageDetail>();
    const client = adapter({
      listMessages: vi.fn().mockResolvedValue({
        items: [message({ id: 'message-1' }), message({ id: 'message-2' })],
        total: 2,
      }),
      getMessage: vi.fn((_, messageId: string) =>
        messageId === 'message-1'
          ? firstDetail.promise
          : Promise.resolve(detail({ id: 'message-2', subject: 'Second' })),
      ),
    });
    const { result } = renderController({ client });

    await waitFor(() =>
      expect(result.current.state.selectedMessageId).toBe('message-1'),
    );
    act(() => {
      result.current.actions.selectMessage('message-2');
    });
    await waitFor(() =>
      expect(result.current.state.detail?.id).toBe('message-2'),
    );

    await act(async () => {
      firstDetail.resolve(detail({ id: 'message-1', subject: 'First' }));
      await firstDetail.promise;
    });

    expect(result.current.state.detail?.id).toBe('message-2');
  });
});
