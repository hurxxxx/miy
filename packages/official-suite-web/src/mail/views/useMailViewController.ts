import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

import {
  createMailAccount,
  createReplyDraft,
  getMailMessage,
  listMailAccounts,
  listMailDrafts,
  listMailMessages,
  sendMailDraft,
  summarizeMailMessage,
  syncMailAccount,
  testMailAccount,
  updateMailAccount,
  updateMailDraft,
  updateMailFlags,
  type MailAccountConnectionPayload,
  type MailDraft,
  type MailMessage,
} from '../api/mail-api';
import {
  MAIL_VIEW_INITIAL_STATE,
  mailViewReducer,
  type MailViewState,
} from './mail-view-model';
import {
  createMailAccountCommand,
  loadMailSnapshot,
  sendMailDraftCommand,
  startUnreadDetailReadMark,
  updateMailAccountCommand,
  type MailAdapter,
} from './mail-view-workflow';

export type { MailAdapter } from './mail-view-workflow';

export interface MailViewControllerMessages {
  loadFailed: string;
  messageLoadFailed: string;
  accountCreateFailed: string;
  accountUpdateFailed: string;
  syncFailed: string;
  aiFailed: string;
  sendFailed: string;
  accountConnected: string;
  accountUpdated: string;
  syncQueued: string;
  draftCreated: string;
  draftSent: string;
}

export interface MailViewControllerNotify {
  success(message: string): void;
}

export interface MailViewControllerOptions {
  token: string | null;
  view: 'messages' | 'drafts' | 'settings';
  unread: boolean;
  starred: boolean;
  messages: MailViewControllerMessages;
  notify: MailViewControllerNotify;
  client?: MailAdapter;
}

export interface MailViewController {
  state: MailViewState;
  selectedDraft: MailDraft | null;
  actions: {
    refresh(nextQuery?: string): Promise<void>;
    setQuery(query: string): void;
    selectMessage(messageId: string | null): void;
    selectDraft(draftId: string | null): void;
    setAccountForm(accountForm: MailAccountConnectionPayload): void;
    setAccountEditForm(
      accountId: string,
      form: MailAccountConnectionPayload,
    ): void;
    createAccount(): Promise<void>;
    updateAccount(accountId: string): Promise<void>;
    syncAccount(accountId: string): Promise<void>;
    starMessage(message: MailMessage): Promise<void>;
    summarizeMessage(): Promise<void>;
    setReplyInstruction(replyInstruction: string): void;
    createReplyDraft(): Promise<void>;
    changeDraft(draft: MailDraft | null): void;
    sendDraft(draft: MailDraft | null): Promise<void>;
  };
}

export const mailAdapter: MailAdapter = {
  listAccounts: listMailAccounts,
  listMessages: listMailMessages,
  listDrafts: listMailDrafts,
  getMessage: getMailMessage,
  updateFlags: updateMailFlags,
  testAccount: testMailAccount,
  createAccount: createMailAccount,
  updateAccount: updateMailAccount,
  syncAccount: syncMailAccount,
  summarizeMessage: summarizeMailMessage,
  createReplyDraft,
  updateDraft: updateMailDraft,
  sendDraft: sendMailDraft,
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useMailViewController({
  token,
  view,
  unread,
  starred,
  messages,
  notify,
  client = mailAdapter,
}: MailViewControllerOptions): MailViewController {
  const [state, dispatch] = useReducer(
    mailViewReducer,
    MAIL_VIEW_INITIAL_STATE,
  );
  const session = useMemo(
    () => ({ controller: new AbortController() }),
    [token, client],
  );
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const captureSession = useCallback(() => {
    const signal = session.controller.signal;
    return () => sessionRef.current === session && !signal.aborted;
  }, [session]);
  useEffect(() => {
    // StrictMode may replay setup after cleanup; old calls retain the aborted signal.
    if (session.controller.signal.aborted)
      session.controller = new AbortController();
    dispatch({ type: 'resetSession' });
    return () => session.controller.abort();
  }, [session]);
  const viewScope = useMemo(() => ({ view }), [view]);
  const viewScopeRef = useRef(viewScope);
  viewScopeRef.current = viewScope;
  const listScope = useMemo(
    () => ({ view, unread, starred }),
    [view, unread, starred],
  );
  const listScopeRef = useRef(listScope);
  listScopeRef.current = listScope;
  const messageSelection = useMemo(
    () => ({ id: state.selectedMessageId, view }),
    [state.selectedMessageId, view],
  );
  const draftSelection = useMemo(
    () => ({ id: state.selectedDraftId, view }),
    [state.selectedDraftId, view],
  );
  const messageSelectionRef = useRef(messageSelection);
  const draftSelectionRef = useRef(draftSelection);
  messageSelectionRef.current = messageSelection;
  draftSelectionRef.current = draftSelection;
  const loadSequence = useRef(0);
  const queryRef = useRef(state.query);
  queryRef.current = state.query;
  const selectedDraft = useMemo(
    () =>
      state.drafts.find((draft) => draft.id === state.selectedDraftId) ?? null,
    [state.drafts, state.selectedDraftId],
  );

  const loadAll = useCallback(
    async (nextQuery?: string) => {
      const sessionIsCurrent = captureSession();
      const isCurrent = () =>
        sessionIsCurrent() && listScopeRef.current === listScope;
      if (!token || !isCurrent()) return;
      const sequence = ++loadSequence.current;
      const queryForRequest = nextQuery ?? queryRef.current;
      dispatch({ type: 'setError', error: null });
      try {
        const snapshot = await loadMailSnapshot({
          adapter: client,
          token,
          query: queryForRequest,
          unread,
          starred,
        });
        if (!isCurrent() || sequence !== loadSequence.current) return;
        dispatch({ type: 'loadSuccess', ...snapshot });
      } catch (err) {
        if (!isCurrent() || sequence !== loadSequence.current) return;
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.loadFailed),
        });
      }
    },
    [
      captureSession,
      client,
      listScope,
      messages.loadFailed,
      starred,
      token,
      unread,
    ],
  );

  const refresh = loadAll;

  useEffect(() => {
    void refresh();
  }, [refresh, view]);

  useEffect(() => {
    if (!token || !state.selectedMessageId || view !== 'messages') {
      dispatch({ type: 'clearDetail' });
      return;
    }
    const sessionIsCurrent = captureSession();
    const selection = messageSelectionRef.current;
    const isCurrent = () =>
      sessionIsCurrent() && messageSelectionRef.current === selection;
    let cancelled = false;
    dispatch({ type: 'messageLoadStart' });
    client
      .getMessage(token, state.selectedMessageId)
      .then((message) => {
        if (cancelled || !isCurrent()) return;
        dispatch({ type: 'messageLoadSuccess', message });
        const readMark = startUnreadDetailReadMark(
          { adapter: client, token },
          message,
        );
        if (readMark.status === 'pending') {
          dispatch({
            type: 'messageReadOptimistic',
            message: readMark.optimistic,
          });
          void readMark.commit.then((outcome) => {
            if (cancelled || !isCurrent()) return;
            if (outcome.status === 'updated') {
              dispatch({ type: 'messageFlagUpdate', message: outcome.message });
            } else {
              dispatch({
                type: 'messageFlagRollback',
                message: outcome.message,
              });
            }
          });
        }
      })
      .catch((err) => {
        if (cancelled || !isCurrent()) return;
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.messageLoadFailed),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [
    captureSession,
    client,
    messages.messageLoadFailed,
    state.selectedMessageId,
    token,
    view,
  ]);

  const createAccountAction = useCallback(async () => {
    const sessionIsCurrent = captureSession();
    const isCurrent = () =>
      sessionIsCurrent() && viewScopeRef.current === viewScope;
    if (!token || !isCurrent()) return;
    dispatch({ type: 'setBusy', busy: true });
    dispatch({ type: 'setError', error: null });
    try {
      const result = await createMailAccountCommand(
        { adapter: client, token, isCurrent },
        state.accountForm,
      );
      if (!isCurrent()) return;
      if (result.status === 'connection-failed') {
        dispatch({
          type: 'setError',
          error: result.message,
        });
        return;
      }
      dispatch({ type: 'resetAccountForm' });
      notify.success(messages.accountConnected);
      await loadAll();
    } catch (err) {
      if (!isCurrent()) return;
      dispatch({
        type: 'setError',
        error: errorMessage(err, messages.accountCreateFailed),
      });
    } finally {
      if (sessionIsCurrent()) dispatch({ type: 'setBusy', busy: false });
    }
  }, [
    captureSession,
    viewScope,
    client,
    loadAll,
    messages.accountConnected,
    messages.accountCreateFailed,
    notify,
    state.accountForm,
    token,
  ]);

  const updateAccountAction = useCallback(
    async (accountId: string) => {
      const isCurrent = captureSession();
      if (!token || !isCurrent()) return;
      const form = state.accountEditForms[accountId];
      if (!form) return;
      dispatch({ type: 'setBusy', busy: true });
      dispatch({ type: 'setError', error: null });
      try {
        const updated = await updateMailAccountCommand(
          { adapter: client, token, isCurrent },
          accountId,
          form,
        );
        if (!isCurrent()) return;
        dispatch({ type: 'accountUpdated', account: updated });
        notify.success(messages.accountUpdated);
        await loadAll();
      } catch (err) {
        if (!isCurrent()) return;
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.accountUpdateFailed),
        });
      } finally {
        if (isCurrent()) dispatch({ type: 'setBusy', busy: false });
      }
    },
    [
      captureSession,
      client,
      loadAll,
      messages.accountUpdateFailed,
      messages.accountUpdated,
      notify,
      state.accountEditForms,
      token,
    ],
  );

  const syncAccountAction = useCallback(
    async (accountId: string) => {
      const isCurrent = captureSession();
      if (!token || !isCurrent()) return;
      dispatch({ type: 'setBusy', busy: true });
      dispatch({ type: 'setError', error: null });
      try {
        const response = await client.syncAccount(token, accountId);
        if (!isCurrent()) return;
        dispatch({ type: 'accountUpdated', account: response.account });
        notify.success(messages.syncQueued);
        await loadAll();
      } catch (err) {
        if (!isCurrent()) return;
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.syncFailed),
        });
      } finally {
        if (isCurrent()) dispatch({ type: 'setBusy', busy: false });
      }
    },
    [
      captureSession,
      client,
      loadAll,
      messages.syncFailed,
      messages.syncQueued,
      notify,
      token,
    ],
  );

  const starMessage = useCallback(
    async (message: MailMessage) => {
      const isCurrent = captureSession();
      if (!token || !isCurrent()) return;
      const optimistic = { ...message, is_starred: !message.is_starred };
      dispatch({ type: 'messageFlagUpdate', message: optimistic });
      try {
        const updated = await client.updateFlags(token, message.id, {
          is_starred: optimistic.is_starred,
        });
        if (!isCurrent()) return;
        dispatch({ type: 'messageFlagUpdate', message: updated });
      } catch (err) {
        if (!isCurrent()) return;
        dispatch({ type: 'messageFlagRollback', message });
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.loadFailed),
        });
      }
    },
    [captureSession, client, messages.loadFailed, token],
  );

  const summarizeMessageAction = useCallback(async () => {
    const sessionIsCurrent = captureSession();
    const isCurrent = () =>
      sessionIsCurrent() && messageSelectionRef.current === messageSelection;
    if (
      !token ||
      !state.detail ||
      state.detail.id !== state.selectedMessageId ||
      !isCurrent()
    )
      return;
    dispatch({ type: 'setBusy', busy: true });
    dispatch({ type: 'setError', error: null });
    try {
      const result = await client.summarizeMessage(token, state.detail.id);
      if (!isCurrent()) return;
      dispatch({ type: 'setSummary', summary: result.summary });
    } catch (err) {
      if (!isCurrent()) return;
      dispatch({
        type: 'setError',
        error: errorMessage(err, messages.aiFailed),
      });
    } finally {
      if (sessionIsCurrent()) dispatch({ type: 'setBusy', busy: false });
    }
  }, [
    captureSession,
    messageSelection,
    state.selectedMessageId,
    client,
    messages.aiFailed,
    state.detail,
    token,
  ]);

  const createReplyDraftAction = useCallback(async () => {
    const sessionIsCurrent = captureSession();
    const isCurrent = () =>
      sessionIsCurrent() && messageSelectionRef.current === messageSelection;
    if (
      !token ||
      !state.detail ||
      state.detail.id !== state.selectedMessageId ||
      !isCurrent()
    )
      return;
    dispatch({ type: 'setBusy', busy: true });
    dispatch({ type: 'setError', error: null });
    try {
      const draft = await client.createReplyDraft(
        token,
        state.detail.id,
        state.replyInstruction,
      );
      if (!isCurrent()) return;
      dispatch({ type: 'draftUpsert', draft, select: true });
      notify.success(messages.draftCreated);
    } catch (err) {
      if (!isCurrent()) return;
      dispatch({
        type: 'setError',
        error: errorMessage(err, messages.aiFailed),
      });
    } finally {
      if (sessionIsCurrent()) dispatch({ type: 'setBusy', busy: false });
    }
  }, [
    captureSession,
    messageSelection,
    state.selectedMessageId,
    client,
    messages.aiFailed,
    messages.draftCreated,
    notify,
    state.detail,
    state.replyInstruction,
    token,
  ]);

  const sendDraftAction = useCallback(
    async (draft: MailDraft | null) => {
      const sessionIsCurrent = captureSession();
      const isCurrent = () =>
        sessionIsCurrent() && draftSelectionRef.current === draftSelection;
      if (
        !token ||
        !draft ||
        draft.id !== state.selectedDraftId ||
        !isCurrent()
      )
        return;
      dispatch({ type: 'setBusy', busy: true });
      dispatch({ type: 'setError', error: null });
      try {
        const sent = await sendMailDraftCommand(
          { adapter: client, token, isCurrent },
          draft,
        );
        if (!isCurrent()) return;
        dispatch({ type: 'draftUpsert', draft: sent });
        notify.success(messages.draftSent);
      } catch (err) {
        if (!isCurrent()) return;
        dispatch({
          type: 'setError',
          error: errorMessage(err, messages.sendFailed),
        });
      } finally {
        if (sessionIsCurrent()) dispatch({ type: 'setBusy', busy: false });
      }
    },
    [
      captureSession,
      draftSelection,
      state.selectedDraftId,
      client,
      messages.draftSent,
      messages.sendFailed,
      notify,
      token,
    ],
  );

  const actions = useMemo<MailViewController['actions']>(
    () => ({
      refresh,
      setQuery: (query) => dispatch({ type: 'setQuery', query }),
      selectMessage: (messageId) =>
        dispatch({ type: 'setSelectedMessageId', messageId }),
      selectDraft: (draftId) =>
        dispatch({ type: 'setSelectedDraftId', draftId }),
      setAccountForm: (accountForm) =>
        dispatch({ type: 'setAccountForm', accountForm }),
      setAccountEditForm: (accountId, form) =>
        dispatch({ type: 'setAccountEditForm', accountId, form }),
      createAccount: createAccountAction,
      updateAccount: updateAccountAction,
      syncAccount: syncAccountAction,
      starMessage,
      summarizeMessage: summarizeMessageAction,
      setReplyInstruction: (replyInstruction) =>
        dispatch({ type: 'setReplyInstruction', replyInstruction }),
      createReplyDraft: createReplyDraftAction,
      changeDraft: (draft) => dispatch({ type: 'draftChange', draft }),
      sendDraft: sendDraftAction,
    }),
    [
      createAccountAction,
      createReplyDraftAction,
      refresh,
      sendDraftAction,
      starMessage,
      summarizeMessageAction,
      syncAccountAction,
      updateAccountAction,
    ],
  );

  return {
    state,
    selectedDraft,
    actions,
  };
}
