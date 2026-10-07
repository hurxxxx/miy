import { RegistrationAuthorization } from './registration-authorization';
import { AgentTree, ManagementView, useOverview } from './management';
import { PageLayout } from './page-layout';
import { SessionsView, type SessionFilters } from './sessions';
import { useConversationViewport } from './conversation-viewport';
import { Button, Dialog, Input } from '@miy/ui';
import {
  Activity,
  Boxes,
  ArrowUp,
  ArrowLeft,
  MessagesSquare,
  CircleStop,
  Code2,
  BookOpen,
  ListTodo,
  LogOut,
  Menu,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  active,
  api,
  apiBasePath,
  ApiError,
  consumeMIYSessionHandoff,
  locked,
  record,
  uploadAttachment,
  type Account,
  type Model,
  type Skill,
  type Attachment,
  type Detail,
  type DeviceLogin,
  type Revision,
  type Task,
  type Thread,
  type ThreadPage,
} from './api';
import {
  errorCopy,
  statusCopy,
  translate,
  type Copy,
  type Locale,
} from './i18n';
import {
  Command,
  Confirm,
  Documents,
  MessageItem,
  RequestForm,
  type DocumentDraft,
} from './views';
import { AttachmentBadges, FileLibrary } from './attachments';
import { CodexUpdateGuide } from './codex-update';
import { Templates } from './templates';
import {
  WorkbenchApps,
  WorkbenchPlatform,
  type StartWorkbenchTask,
} from './workbench';
import { Instructions } from './instructions';
import { AgentActivity } from './agent-activity';
import { needsAttention, executing, running } from './agent-state';
import { GitWorkspace, GitSummary, useGitState } from './git';
import {
  ExecutionSettings,
  ExecutionStatus,
  PermissionSelect,
  resolveExecution,
  type Execution,
} from './execution';

type Tab = 'plan' | 'branch' | 'checks' | 'files';
const tabs: { id: Tab; label: Copy }[] = [
  { id: 'plan', label: 'Plan' },
  { id: 'branch', label: 'Branch' },
  { id: 'checks', label: 'Execution results' },
  { id: 'files', label: 'Files' },
];

type SessionTab = 'sessions' | 'codex' | null;
type ConsolePage =
  | 'studio'
  | 'apps'
  | 'platform'
  | 'sessions'
  | 'workspace'
  | 'templates'
  | 'instructions'
  | 'monitoring';
function readRoute(): {
  page: ConsolePage;
  task: string | null;
  sessionTab: SessionTab;
  template: string | null;
} {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get('task');
  const task = raw && /^[0-9a-f-]{36}$/.test(raw) ? raw : null;
  const view = params.get('view');
  const tab = params.get('tab');
  const page: ConsolePage = task
    ? 'workspace'
    : tab === 'codex'
      ? 'sessions'
      : view === 'templates' ||
          view === 'monitoring' ||
          view === 'instructions' ||
          view === 'studio' ||
          view === 'apps' ||
          view === 'platform' ||
          view === 'sessions'
        ? view
        : view === 'agents' || view === 'history' || view === 'workspace'
          ? 'sessions'
          : 'studio';
  const template = params.get('template');
  return {
    page,
    task,
    sessionTab:
      page === 'sessions' ? (tab === 'codex' ? 'codex' : 'sessions') : null,
    template:
      page === 'sessions' &&
      tab !== 'codex' &&
      template &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        template,
      )
        ? template.toLowerCase()
        : null,
  };
}

export function App() {
  const [locale, setLocale] = useState<Locale>('ko-KR');
  const t = useMemo(() => translate(locale), [locale]);
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [sessionFailed, setSessionFailed] = useState(false);
  const [password, setPassword] = useState('');
  const [page, setPage] = useState<ConsolePage>(() => readRoute().page);
  const [isolate, setIsolate] = useState(false);
  const drafts = useRef(new Map<string, string>());
  const selectionDrafts = useRef(
    new Map<string, { attachmentIds: string[]; skillNames: string[] }>(),
  );
  const workspaceHeading = useRef<HTMLHeadingElement>(null);
  const focusSession = useRef(false);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [overviewCheckedAt, setOverviewCheckedAt] = useState<number | null>(
    null,
  );
  const [overviewFailed, setOverviewFailed] = useState(false);
  const overviewRequest = useRef(0);
  const [task, setTask] = useState<Detail | null>(null);
  const [documentDrafts, setDocumentDrafts] = useState<
    Record<string, DocumentDraft>
  >({});
  const [selected, setSelected] = useState<string | null>(() => {
    const id = new URLSearchParams(window.location.search).get('task');
    return id && /^[0-9a-f-]{36}$/.test(id) ? id : null;
  });
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [tab, setTab] = useState<Tab>('plan');
  const [mobileView, setMobileView] = useState<'conversation' | 'results'>(
    'conversation',
  );
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [sessionFilters, setSessionFilters] = useState<SessionFilters>({
    status: 'all',
    source: 'all',
    query: '',
  });
  const [sessionTab, setSessionTab] = useState<SessionTab>(
    () => readRoute().sessionTab,
  );
  const sessionScroll = useRef(0);
  const [templateId, setTemplateId] = useState(() => readRoute().template);
  const [history, setHistory] = useState<Thread[]>([]);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [historySearch, setHistorySearch] = useState('');
  const [importThread, setImportThread] = useState<Thread | null>(null);
  const [confirmInactive, setConfirmInactive] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [skillCatalog, setSkillCatalog] = useState<{
    taskId: string;
    items: Skill[];
  } | null>(null);
  const skills = skillCatalog?.taskId === selected ? skillCatalog.items : [];
  const [selectedSkillNames, setSkillNames] = useState<string[]>([]);
  const skillNames = selectedSkillNames.filter((name) =>
    skills.some((skill) => skill.name === name),
  );
  const [stage, setStage] = useState<'plan' | 'implement'>('plan');
  const git = useGitState(task);
  const [models, setModels] = useState<Model[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [updateGuideOpen, setUpdateGuideOpen] = useState(false);
  const versionMismatch = [modelsError, account?.error_code, error].includes(
    'codex_version_mismatch',
  );
  const [execution, setExecution] = useState<Execution>({
    model: null,
    effort: null,
    permissions: 'ask',
  });
  const selectedExecution = useMemo(
    () =>
      resolveExecution(
        {
          ...execution,
          model: execution.model ?? task?.model ?? null,
          effort:
            execution.effort ??
            (execution.model ? null : (task?.effort ?? null)),
        },
        models,
      ),
    [execution, models, task?.model, task?.effort],
  );
  const [approvalExecution, setApprovalExecution] =
    useState<Execution>(execution);
  const approvalDisplay = resolveExecution(
    {
      ...approvalExecution,
      model: approvalExecution.model ?? task?.model ?? null,
      effort:
        approvalExecution.effort ??
        (approvalExecution.model ? null : (task?.effort ?? null)),
    },
    models,
  );
  const [approvalText, setApprovalText] = useState('');
  const initializedTask = useRef<string | null>(null);
  const [planToApprove, setPlanToApprove] = useState<Revision | null>(null);
  const [selectedAttachmentIds, setAttachmentIds] = useState<string[]>([]);
  // Only current server metadata may supply executable inputs. Keep selections
  // in memory while loading, without sending removed or another task's files.
  const attachmentIds = selectedAttachmentIds.filter(
    (id) =>
      task?.id === selected &&
      task.attachments.some((file) => file.id === id && !file.deleted),
  );
  const [attachmentPicker, setAttachmentPicker] = useState(false);
  const [approvalFiles, setApprovalFiles] = useState<Attachment[]>([]);
  const [fileToDelete, setFileToDelete] = useState<Attachment | null>(null);
  const uploadAbort = useRef<AbortController | null>(null);
  const uploadIds = useRef(new WeakMap<File, string>());
  const [uploads, setUploads] = useState<
    { file: File; progress: number; failed: boolean; select: boolean }[]
  >([]);
  const [connected, setConnected] = useState(false);
  const [device, setDevice] = useState<DeviceLogin | null>(null);
  const [usageOpen, setUsageOpen] = useState(false);
  const requestKeys = useRef(new Map<string, string>());
  const sessionInitialization = useRef<Promise<void> | null>(null);
  const conversationViewport = useConversationViewport(
    task?.id ?? null,
    task?.event_id,
    authenticated === true,
    `${page}:${sessionTab}:${mobileView}`,
  );
  const rememberComposer = useCallback(() => {
    if (!selected) return;
    drafts.current.set(selected, message);
    selectionDrafts.current.set(selected, {
      attachmentIds: selectedAttachmentIds,
      skillNames: selectedSkillNames,
    });
  }, [selected, message, selectedAttachmentIds, selectedSkillNames]);
  useEffect(() => {
    if (authenticated !== false) return;
    drafts.current.clear();
    selectionDrafts.current.clear();
    setMessage('');
    setAttachmentIds([]);
    setSkillNames([]);
  }, [authenticated]);

  const onError = useCallback((value: unknown) => {
    const code = value instanceof ApiError ? value.code : 'request_failed';
    setError(code);
    if (code === 'unauthenticated') {
      setAuthenticated(false);
      setTask(null);
      setTasks([]);
    }
  }, []);
  const checkSession = useCallback(async () => {
    setSessionFailed(false);
    setError(null);
    try {
      const value = await api<{ authenticated: boolean }>('/session');
      setAuthenticated(value.authenticated);
    } catch (error) {
      setSessionFailed(true);
      onError(error);
    }
  }, [onError]);
  const initializeSession = useCallback(async () => {
    const handoff = consumeMIYSessionHandoff();
    if (!handoff) {
      await checkSession();
      return;
    }
    setSessionFailed(false);
    setError(null);
    try {
      const value = await api<{ authenticated: boolean }>(
        '/session/miy',
        handoff,
      );
      setAuthenticated(value.authenticated);
    } catch {
      await checkSession();
    }
  }, [checkSession]);
  const refreshTasks = useCallback(async () => {
    const request = ++overviewRequest.current;
    try {
      const rows = await api<Task[]>('/overview');
      if (request !== overviewRequest.current) return;
      setTasks(rows);
      setOverviewCheckedAt(Date.now());
      setOverviewFailed(false);
    } catch (error) {
      if (request !== overviewRequest.current) return;
      setOverviewFailed(true);
      throw error;
    }
  }, []);
  const refreshAccount = useCallback(async () => {
    const value = await api<Account>('/codex/account');
    setAccount(value);
    if (value.auth_type === 'chatgpt') setDevice(null);
  }, []);
  const refreshModels = useCallback(
    async (taskId: string, signal?: AbortSignal) => {
      setModelsError(null);
      try {
        const rows = await api<Model[]>(
          `/codex/models?task_id=${encodeURIComponent(taskId)}`,
          undefined,
          undefined,
          signal,
        );
        if (!signal?.aborted) setModels(rows);
      } catch (error) {
        if (!signal?.aborted)
          setModelsError(
            error instanceof ApiError ? error.code : 'request_failed',
          );
      }
    },
    [],
  );
  const refreshTask = useCallback(async (id: string, signal?: AbortSignal) => {
    const detail = await api<Detail>(
      `/tasks/${id}`,
      undefined,
      undefined,
      signal,
    );
    if (selectedRef.current === id)
      setTask((current) =>
        current?.id === id && current.event_id > detail.event_id
          ? current
          : detail,
      );
  }, []);
  const act = useCallback(
    async (operation: () => Promise<void>) => {
      if (busyRef.current) return false;
      busyRef.current = true;
      setBusy(true);
      setError(null);
      try {
        await operation();
        return true;
      } catch (err) {
        onError(err);
        return false;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [onError],
  );
  const mutate = useCallback(
    async (suffix: string, body: unknown, method?: string) => {
      const id = selectedRef.current;
      if (!id) return false;
      return act(async () => {
        await api(`/tasks/${id}/${suffix}`, body, method);
        if (suffix === 'recover') {
          // Only explicit, successful recovery permits a fresh submission. Keep
          // other tasks' retry identities and never replay an uncertain request.
          for (const key of requestKeys.current.keys()) {
            if (JSON.parse(key)[0] === id) requestKeys.current.delete(key);
          }
        }
        await refreshTask(id);
        await refreshTasks();
      });
    },
    [act, refreshTask, refreshTasks],
  );
  const send = useCallback(
    async (
      suffix: string,
      data: Record<string, unknown>,
      requestedTaskId?: string,
    ) => {
      const taskId = requestedTaskId ?? selectedRef.current;
      if (!taskId) return false;
      const payload = { attachment_ids: attachmentIds, ...data };
      const key = JSON.stringify([taskId, suffix, payload]);
      const id = requestKeys.current.get(key) ?? crypto.randomUUID();
      requestKeys.current.set(key, id);
      const ok = await act(async () => {
        const detail = await api<Detail>(`/tasks/${taskId}/${suffix}`, {
          ...payload,
          operation_id: id,
        });
        requestKeys.current.delete(key);
        const saved = selectionDrafts.current.get(taskId);
        if (saved) {
          const submitted = new Set(payload.attachment_ids);
          selectionDrafts.current.set(taskId, {
            ...saved,
            attachmentIds: saved.attachmentIds.filter(
              (id) => !submitted.has(id),
            ),
          });
        }
        if (drafts.current.get(taskId) === data.text)
          drafts.current.delete(taskId);
        if (selectedRef.current === taskId) {
          setTask((current) =>
            current?.id === taskId && current.event_id > detail.event_id
              ? current
              : detail,
          );
          setAttachmentIds([]);
        }
        await refreshTasks().catch(onError);
      });
      return ok;
    },
    [act, attachmentIds, refreshTasks, onError],
  );

  const overviewChanged = useCallback(() => {
    void refreshTasks().catch(onError);
  }, [refreshTasks, onError]);
  useOverview(authenticated === true, overviewChanged);
  const approveImplementation = (revision: Revision, text = '') => {
    if (!task) return;
    setApprovalFiles(
      task.attachments.filter((file) => attachmentIds.includes(file.id)),
    );
    setApprovalExecution(execution);
    setApprovalText(text);
    setPlanToApprove(revision);
  };

  const toggleAttachment = (id: string) => {
    if (attachmentIds.includes(id))
      setAttachmentIds(attachmentIds.filter((value) => value !== id));
    else if (attachmentIds.length < (task?.attachment_limits.selection ?? 20))
      setAttachmentIds([...attachmentIds, id]);
    else setError('attachment_selection_limit');
  };
  const uploadFiles = async (files: File[], select: boolean) => {
    const taskId = selectedRef.current;
    if (!taskId || !files.length) return;
    await act(async () => {
      setAttachmentIds(attachmentIds);
      const controller = new AbortController();
      uploadAbort.current = controller;
      try {
        for (const file of files) {
          if (controller.signal.aborted || selectedRef.current !== taskId)
            break;
          const id = uploadIds.current.get(file) ?? crypto.randomUUID();
          uploadIds.current.set(file, id);
          setUploads((rows) => [
            ...rows.filter((row) => row.file !== file),
            { file, progress: 0, failed: false, select },
          ]);
          try {
            if (file.size > (task?.attachment_limits.file_bytes ?? 0))
              throw new ApiError('attachment_too_large');
            const result = await uploadAttachment(
              taskId,
              id,
              file,
              controller.signal,
              (progress) => {
                if (selectedRef.current === taskId)
                  setUploads((rows) =>
                    rows.map((row) =>
                      row.file === file ? { ...row, progress } : row,
                    ),
                  );
              },
            );
            if (selectedRef.current !== taskId) break;
            setUploads((rows) => rows.filter((row) => row.file !== file));
            if (select)
              setAttachmentIds((ids) =>
                ids.includes(result.id) ||
                ids.length >= (task?.attachment_limits.selection ?? 20)
                  ? ids
                  : [...ids, result.id],
              );
            await refreshTask(taskId);
          } catch (error) {
            if (selectedRef.current !== taskId) break;
            setUploads((rows) =>
              rows.map((row) =>
                row.file === file ? { ...row, failed: true } : row,
              ),
            );
            onError(
              controller.signal.aborted
                ? new ApiError('attachment_upload_cancelled')
                : error,
            );
          }
        }
      } finally {
        if (uploadAbort.current === controller) uploadAbort.current = null;
      }
    });
  };

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  useEffect(() => {
    if (!sidebarOpen) return;
    const buttons = () =>
      Array.from(
        sidebar.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]',
        ) ?? [],
      );
    buttons()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSidebarOpen(false);
        menuButton.current?.focus();
      } else if (event.key === 'Tab') {
        const controls = buttons();
        const target = event.shiftKey ? controls.at(-1) : controls[0];
        const edge = event.shiftKey ? controls[0] : controls.at(-1);
        if (document.activeElement === edge && target) {
          event.preventDefault();
          target.focus();
        }
      }
    };
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, [sidebarOpen]);
  useEffect(() => {
    if (
      !Object.values(documentDrafts).some(
        (draft) => draft.body !== (draft.base?.body ?? ''),
      )
    )
      return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [documentDrafts]);
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () =>
      document.documentElement.classList.toggle('dark', media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    sessionInitialization.current ??= initializeSession();
    void sessionInitialization.current;
  }, [initializeSession]);
  useEffect(() => {
    if (!authenticated) return;
    void refreshTasks().catch(onError);
    void refreshAccount().catch(onError);
    const timer = window.setInterval(
      () => void refreshAccount().catch(onError),
      30000,
    );
    return () => window.clearInterval(timer);
  }, [authenticated, refreshTasks, refreshAccount, onError]);
  useEffect(() => {
    if (!authenticated || !selected) return;
    const controller = new AbortController();
    setModels([]);
    void refreshModels(selected, controller.signal);
    return () => controller.abort();
  }, [authenticated, selected, refreshModels]);
  useEffect(() => {
    initializedTask.current = null;
    setTask(null);
    setMessage(selected ? (drafts.current.get(selected) ?? '') : '');
    setSkillCatalog(null);
    const savedSelection = selected
      ? selectionDrafts.current.get(selected)
      : undefined;
    setSkillNames(savedSelection?.skillNames ?? []);
    if (selected) drafts.current.delete(selected);
    uploadAbort.current?.abort();
    setUploads([]);
    setAttachmentIds(savedSelection?.attachmentIds ?? []);
    setAttachmentPicker(false);
    setFileToDelete(null);
    setApprovalFiles([]);
    setConnected(false);
    setPlanToApprove(null);
    if (!selected || !authenticated) return;
    const controller = new AbortController();
    void api<Skill[]>(
      `/tasks/${selected}/skills`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted)
          setSkillCatalog({ taskId: selected, items: value });
      })
      .catch(() => {
        /* The model connection control already displays connection failures. */
      });
    void refreshTask(selected, controller.signal).catch((err) => {
      if (!controller.signal.aborted) onError(err);
    });
    const stream = new EventSource(`${apiBasePath}/tasks/${selected}/events`);
    const refresh = () => {
      void refreshTask(selected, controller.signal).catch((err) => {
        if (!controller.signal.aborted) onError(err);
      });
      void refreshTasks().catch(onError);
    };
    const fallback = window.setInterval(refresh, 10000);
    const visible = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', visible);
    stream.addEventListener('changed', refresh);
    stream.addEventListener('open', () => {
      setConnected(true);
      refresh();
    });
    stream.addEventListener('error', () => setConnected(false));
    stream.addEventListener('expired', () => {
      stream.close();
      setAuthenticated(false);
      setTask(null);
    });
    return () => {
      window.clearInterval(fallback);
      document.removeEventListener('visibilitychange', visible);
      controller.abort();
      uploadAbort.current?.abort();
      stream.close();
    };
  }, [selected, authenticated, refreshTask, refreshTasks, onError]);
  useEffect(() => {
    if (!task || initializedTask.current === task.id) return;
    initializedTask.current = task.id;
    setStage(
      task.stage === 'review' || task.stage === 'implement'
        ? 'implement'
        : 'plan',
    );
    setExecution({
      model: null,
      effort: null,
      permissions: task.permissions === 'yolo' ? 'yolo' : 'ask',
    });
  }, [task]);

  const loadHistory = async (cursor: string | null = null) => {
    await act(async () => {
      const result = await api<ThreadPage>(
        `/codex/threads?search=${encodeURIComponent(historySearch)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`,
      );
      setHistory((rows) =>
        cursor ? [...rows, ...result.items] : result.items,
      );
      setHistoryCursor(result.cursor ?? null);
    });
  };
  const choose = (id: string) => {
    focusSession.current = true;
    rememberComposer();
    setPage('workspace');
    setSessionTab(null);
    window.history.pushState(null, '', `?task=${encodeURIComponent(id)}`);
    setSelected(id);
    setSidebarOpen(false);
    setError(null);
    setMobileView('conversation');
  };
  useEffect(() => {
    if (
      focusSession.current &&
      page === 'workspace' &&
      !sessionTab &&
      !sidebarOpen &&
      task?.id === selected &&
      workspaceHeading.current
    ) {
      workspaceHeading.current.focus({ preventScroll: true });
      focusSession.current = false;
    }
  }, [page, sessionTab, sidebarOpen, task?.id, selected]);
  const navigate = (
    next: ConsolePage,
    tab: SessionTab = null,
    template: string | null = null,
  ) => {
    rememberComposer();
    setPage(next);
    setSessionTab(next === 'sessions' ? (tab ?? 'sessions') : null);
    if (template !== templateId) sessionScroll.current = 0;
    setTemplateId(template);
    setSidebarOpen(false);
    window.history.pushState(
      null,
      '',
      next === 'workspace' && !tab && selected
        ? `?task=${encodeURIComponent(selected)}`
        : `?view=${next}${tab === 'codex' ? '&tab=codex' : ''}${template ? `&template=${encodeURIComponent(template)}` : ''}`,
    );
  };
  const startWorkbenchTask: StartWorkbenchTask = async (
    context,
    title,
    prompt,
  ) => {
    const next = await api<Detail>('/tasks', {
      title,
      context,
      isolate: false,
    });
    drafts.current.set(next.id, prompt);
    choose(next.id);
    await refreshTasks();
  };
  useEffect(() => {
    if (!authenticated || page !== 'sessions' || sessionTab !== 'codex') return;
    const controller = new AbortController();
    void api<ThreadPage>(
      '/codex/threads?search=',
      undefined,
      'GET',
      controller.signal,
    )
      .then((result) => {
        setHistory(result.items);
        setHistoryCursor(result.cursor ?? null);
      })
      .catch((e) => {
        if (!controller.signal.aborted) onError(e);
      });
    return () => controller.abort();
  }, [authenticated, page, sessionTab, onError]);
  useEffect(() => {
    const pop = () => {
      rememberComposer();
      const route = readRoute();
      setPage(route.page);
      setSidebarOpen(false);
      setSessionTab(route.sessionTab);
      if (route.template !== templateId) sessionScroll.current = 0;
      setTemplateId(route.template);
      if (route.task) setSelected(route.task);
    };
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, [rememberComposer, templateId]);
  const sessionNavigation = (
    <div className="history-tabs" role="group" aria-label={t('Session views')}>
      <button
        aria-pressed={sessionTab === 'sessions'}
        onClick={() => navigate('sessions')}
      >
        {t('All sessions')}
      </button>
      <button
        aria-pressed={sessionTab === 'codex'}
        onClick={() => navigate('sessions', 'codex')}
      >
        {t('Import Codex session')}
      </button>
    </div>
  );
  const uploadStatus = uploads.map((upload, index) => (
    <div className="upload-status" key={index} role="status">
      <span>{upload.file.name}</span>
      {upload.failed ? (
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => void uploadFiles([upload.file], upload.select)}
        >
          {t('Retry upload')}
        </Button>
      ) : (
        <>
          <progress
            max={100}
            value={upload.progress}
            aria-label={t('Uploading')}
          />
          <Button variant="ghost" onClick={() => uploadAbort.current?.abort()}>
            {t('Cancel upload')}
          </Button>
        </>
      )}
    </div>
  ));
  const language = (
    <select
      className="language"
      aria-label="Language / 언어"
      value={locale}
      onChange={(event) => setLocale(event.target.value as Locale)}
    >
      <option value="ko-KR">한국어</option>
      <option value="en-US">English</option>
    </select>
  );
  const feedback = error && (
    <div className="feedback" role="alert">
      <span>{t(errorCopy(error))}</span>
      <Button
        size="icon"
        variant="ghost"
        aria-label={t('Close')}
        onClick={() => setError(null)}
      >
        <X size={16} />
      </Button>
    </div>
  );
  const taskIsActive = active(task);
  const composerImplementation = task
    ? taskIsActive
      ? task.stage === 'implement'
      : stage === 'implement'
    : false;
  const composerYolo = task
    ? composerImplementation &&
      (taskIsActive
        ? task.permissions === 'yolo'
        : execution.permissions === 'yolo')
    : false;
  const composerPlanningHelp = !!task && stage === 'plan' && !taskIsActive;

  if (!authenticated)
    return (
      <div className="login-page">
        <div className="login-language">{language}</div>
        <main className="login-form">
          <div className="brand-mark">
            <Code2 size={24} />
          </div>
          <p className="eyebrow">MIY WORKBENCH</p>
          <h1>{t('Your private development workspace')}</h1>
          <p className="login-description">
            {t(
              'Use your existing Codex subscription to turn an idea into a reviewed change.',
            )}
          </p>
          {sessionFailed && (
            <Button onClick={() => void checkSession()}>
              {t('Retry connection')}
            </Button>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void act(async () => {
                const result = await api<{ authenticated: boolean }>(
                  '/session',
                  { password },
                );
                setPassword('');
                setAuthenticated(result.authenticated);
              });
            }}
          >
            <label htmlFor="password">{t('Owner password')}</label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={1024}
            />
            <Button
              variant="primary"
              type="submit"
              disabled={busy || authenticated === null}
              fullWidth
            >
              {t('Sign in')}
            </Button>
          </form>
          <small>
            {t(
              'This password protects the console. Your ChatGPT login stays with Codex.',
            )}
          </small>
        </main>
        {feedback}
      </div>
    );

  return (
    <div className="console-shell" data-mobile-view={mobileView}>
      <header className="topbar">
        <Button
          className="mobile-only"
          size="icon"
          variant="ghost"
          aria-label={t('Open navigation')}
          aria-expanded={sidebarOpen}
          aria-controls="console-sidebar"
          ref={menuButton}
          onClick={() => setSidebarOpen(true)}
        >
          <Menu size={18} />
        </Button>
        <div className="brand">
          <Code2 size={21} />
          <strong>MIY Workbench</strong>
        </div>
        <div className="topbar-actions">
          <AgentActivity
            tasks={tasks}
            checkedAt={overviewCheckedAt}
            failed={overviewFailed}
            t={t}
            openTask={choose}
            openSessions={() => navigate('sessions')}
          />
          <button
            className="account-badge"
            onClick={() =>
              versionMismatch ? setUpdateGuideOpen(true) : setUsageOpen(true)
            }
          >
            <span
              className={`dot ${account?.auth_type === 'chatgpt' ? 'online' : ''}`}
            />
            {t(
              versionMismatch
                ? 'Codex update required'
                : account?.auth_type === 'chatgpt'
                  ? 'Subscription connected'
                  : 'Codex unavailable',
            )}
          </button>
          {language}
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('Sign out')}
            onClick={() =>
              void act(async () => {
                await api('/session', undefined, 'DELETE');
                setAuthenticated(false);
                setTask(null);
                setSelected(null);
                setTasks([]);
                setDocumentDrafts({});
              })
            }
          >
            <LogOut size={16} />
          </Button>
        </div>
      </header>
      {sidebarOpen && (
        <button
          className="sidebar-backdrop"
          aria-label={t('Close')}
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        id="console-sidebar"
        ref={sidebar}
        className={`sidebar ${sidebarOpen ? 'open' : ''}`}
      >
        <div className="sidebar-heading">
          <span>{t('Develop, deliver and maintain')}</span>
        </div>
        <Button
          variant="primary"
          size="comfortable"
          onClick={() => setNewOpen(true)}
          fullWidth
        >
          <Plus size={16} />
          {t('New task')}
        </Button>
        <nav
          className="console-navigation"
          aria-label={t('Workbench navigation')}
        >
          {(
            [
              ['studio', 'MIY Studio', Code2],
              ['apps', 'App management center', Boxes],
              ['platform', 'Platform management', Activity],
              ['sessions', 'Sessions', MessagesSquare],
              ['templates', 'Task templates', ListTodo],
              ['instructions', 'Instructions and skills', BookOpen],
              ['monitoring', 'Monitoring', Activity],
            ] as const
          ).map(([id, label, Icon]) => (
            <button
              key={id}
              className={
                [
                  'sessions',
                  'templates',
                  'instructions',
                  'monitoring',
                ].includes(id)
                  ? 'nav-secondary'
                  : undefined
              }
              aria-current={
                page === id || (id === 'sessions' && page === 'workspace')
                  ? 'page'
                  : undefined
              }
              onClick={() => navigate(id)}
            >
              <Icon size={17} />
              <span>{t(label)}</span>
              {id === 'sessions' && tasks.some(needsAttention) && (
                <span className="nav-count">
                  {tasks.filter(needsAttention).length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-summary">
          <small>
            {t('Running')}: {tasks.filter(executing).length}
          </small>
          <small>
            {t('Needs attention')}: {tasks.filter(needsAttention).length}
          </small>
        </div>
        <footer className="sidebar-footer">
          <span className="muted">Codex · ChatGPT</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('Refresh')}
            onClick={() =>
              void act(async () => {
                await refreshTasks();
                await refreshAccount();
                if (selected) await refreshTask(selected);
              })
            }
          >
            <RefreshCw size={14} />
          </Button>
        </footer>
      </aside>
      <Instructions
        active={page === 'instructions'}
        t={t}
        onRequest={async (title, text, requestStage) => {
          const next = await api<Detail>('/tasks', { title, isolate: false });
          drafts.current.set(next.id, text);
          choose(next.id);
          // Reuse operation IDs, uncertainty recovery and the native approval flow.
          const accepted = await send(
            requestStage === 'plan' ? 'messages' : 'implement',
            {
              text,
              ...(requestStage === 'plan' ? { stage: 'plan' } : {}),
              model: null,
              effort: null,
              permissions: 'ask',
              attachment_ids: [],
            },
            next.id,
          );
          if (accepted) {
            drafts.current.delete(next.id);
            if (selectedRef.current === next.id) setMessage('');
          }
        }}
      />
      {page === 'studio' || page === 'apps' ? (
        <WorkbenchApps
          key={page}
          area={page}
          newTask={() => setNewOpen(true)}
          t={t}
          tasks={tasks}
          openTask={choose}
          startTask={startWorkbenchTask}
        />
      ) : page === 'platform' ? (
        <WorkbenchPlatform
          t={t}
          navigate={navigate}
          startTask={startWorkbenchTask}
        />
      ) : page === 'instructions' ? null : page === 'templates' ? (
        <Templates
          t={t}
          openTask={choose}
          onError={onError}
          openHistory={(id) => {
            setSessionFilters({ status: 'all', source: 'all', query: '' });
            navigate('sessions', null, id);
          }}
        />
      ) : page === 'monitoring' ? (
        <ManagementView
          t={t}
          tasks={tasks}
          openTask={choose}
          openTemplates={() => navigate('templates')}
        />
      ) : sessionTab === 'codex' ? (
        <PageLayout
          className="native-history-view"
          navigation={sessionNavigation}
          title={t('Import Codex session')}
          description={t(
            'Browse native Codex sessions and open them in your workspace.',
          )}
        >
          <form
            className="search list-controls"
            onSubmit={(e) => {
              e.preventDefault();
              void loadHistory();
            }}
          >
            <Input
              aria-label={t('Search Codex history')}
              placeholder={t('Search Codex history')}
              value={historySearch}
              onChange={(e) => setHistorySearch(e.target.value)}
            />
            <Button
              size="comfortable"
              type="submit"
              aria-label={t('Search Codex history')}
            >
              <Search size={15} />
            </Button>
          </form>
          <div className="task-list">
            {history.map((row) => (
              <button
                key={row.id}
                className="task-row"
                onClick={() => {
                  setImportThread(row);
                  setConfirmInactive(false);
                }}
              >
                <strong>{row.title}</strong>
                <small>
                  {new Date(row.updated_at * 1000).toLocaleDateString(locale)}
                </small>
              </button>
            ))}
          </div>
          {historyCursor && (
            <Button
              disabled={busy}
              onClick={() => void loadHistory(historyCursor)}
            >
              {t('Load more')}
            </Button>
          )}
        </PageLayout>
      ) : sessionTab === 'sessions' ? (
        <SessionsView
          key={templateId ?? 'all'}
          templateId={templateId}
          clearTemplate={() => navigate('sessions')}
          checkedAt={overviewCheckedAt}
          failed={overviewFailed}
          filters={sessionFilters}
          onFilters={setSessionFilters}
          t={t}
          tasks={tasks}
          selectedTask={selected}
          openTask={choose}
          newTask={() => setNewOpen(true)}
          openTemplates={() => navigate('templates')}
          refresh={refreshTasks}
          onError={onError}
          importSession={() => navigate('sessions', 'codex')}
          scrollPosition={sessionScroll}
        />
      ) : !task ? (
        <main className="welcome">
          <div className="brand-mark">
            <Code2 size={28} />
          </div>
          <h1>{t('Start with what you want to change.')}</h1>
          <p>
            {t(
              'Describe a feature or a problem. Codex will inspect the repository and create a plan.',
            )}
          </p>
          <Button
            variant="primary"
            disabled={!!selected}
            onClick={() => setNewOpen(true)}
          >
            <Plus size={16} />
            {t('New task')}
          </Button>
        </main>
      ) : (
        <main className="workspace">
          <div className="task-header">
            <div>
              <Button
                className="workspace-back"
                variant="ghost"
                onClick={() => navigate('sessions')}
              >
                <ArrowLeft size={14} aria-hidden="true" />
                {t('Back to sessions')}
              </Button>
              <h1 ref={workspaceHeading} tabIndex={-1}>
                {task.title}
              </h1>
              <div className="task-meta">
                <span>{t(statusCopy(task.status))}</span>
                <span>·</span>
                <span title={task.root}>
                  {task.root.split('/').at(-1)}
                  {task.isolated && ` · ${t('Isolated checkout')}`}
                </span>
                <span className="connection">
                  <span className={`dot ${connected ? 'online' : ''}`} />
                  {t(connected ? 'Connected' : 'Reconnecting')}
                </span>
              </div>
              <div className="task-git-summary">
                <GitSummary state={git.state} t={t} />
              </div>
            </div>
            {(task.error_code || task.status === 'uncertain') && (
              <div className="runtime-notice" role="status">
                {t(errorCopy(task.error_code ?? 'codex_request_uncertain'))}
                {(task.status === 'uncertain' ||
                  task.error_code === 'codex_request_uncertain' ||
                  task.error_code === 'workspace_changed') && (
                  <>
                    <small>
                      {t('No request will be automatically replayed.')}
                    </small>
                    <Button
                      disabled={busy}
                      onClick={() => {
                        void mutate('recover', {
                          confirm_workspace: true,
                        });
                      }}
                    >
                      {t('Recover state')}
                    </Button>
                  </>
                )}
              </div>
            )}
          </div>
          <div className="mobile-tabs">
            <button
              aria-pressed={mobileView === 'conversation'}
              onClick={() => setMobileView('conversation')}
            >
              {t('Conversation')}
            </button>
            <button
              aria-pressed={mobileView === 'results'}
              onClick={() => setMobileView('results')}
            >
              {t('Results')}
            </button>
          </div>
          <section className="conversation" aria-label={t('Conversation')}>
            <ExecutionStatus task={task} connected={connected} t={t} />
            <details className="task-agents">
              <summary>
                {t('Show agent activity')} ({task.agents?.length ?? 0})
              </summary>
              <AgentTree agents={task.agents ?? []} t={t} />
            </details>
            <div
              className="messages"
              ref={conversationViewport.ref}
              tabIndex={0}
              onScroll={conversationViewport.onScroll}
            >
              {task.context?.purpose === 'registration' && (
                <RegistrationAuthorization key={task.id} task={task} t={t} />
              )}
              {!task.items.length && (
                <div className="conversation-empty">
                  <Code2 size={26} />
                  <h2>{t('Start with what you want to change.')}</h2>
                  <p>
                    {t(
                      'Describe a feature or a problem. Codex will inspect the repository and create a plan.',
                    )}
                  </p>
                </div>
              )}
              {task.history_truncated && (
                <p className="muted">
                  {t(
                    'Showing the latest 2,000 items. The full conversation remains in Codex.',
                  )}
                </p>
              )}
              {task.items.map((item, i) => (
                <MessageItem
                  key={typeof item.id === 'string' ? item.id : i}
                  item={item}
                  t={t}
                  taskId={task.id}
                />
              ))}
              {task.requests.map((request) => (
                <div key={request.id}>
                  <p className="muted">
                    {t('Source agent')}:{' '}
                    {task.agents.find(
                      (a) => a.thread_id === request.payload.threadId,
                    )?.name ?? 'Codex'}
                  </p>
                  <RequestForm
                    key={request.id}
                    request={request}
                    t={t}
                    disabled={busy}
                    onAnswer={(id, response) =>
                      void mutate(`requests/${id}`, response)
                    }
                  />
                </div>
              ))}
            </div>
            <form
              className="composer"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (!busy && task.status !== 'uncertain')
                  void uploadFiles(Array.from(event.dataTransfer.files), true);
              }}
              onSubmit={(event) => {
                event.preventDefault();
                void send(
                  active(task)
                    ? 'steer'
                    : stage === 'implement'
                      ? 'implement'
                      : 'messages',
                  {
                    text: message,
                    skill_names: skillNames,
                    ...(active(task)
                      ? {}
                      : {
                          ...execution,
                          ...(stage === 'plan' ? { stage } : {}),
                        }),
                  },
                ).then((ok) => {
                  if (ok && selectedRef.current === task.id) {
                    setExecution((current) => ({
                      ...current,
                      model: null,
                      effort: null,
                    }));
                    setMessage((current) =>
                      current === message ? '' : current,
                    );
                  }
                });
              }}
            >
              {task.failed_request_text && !message && (
                <Button
                  variant="ghost"
                  type="button"
                  onClick={() => setMessage(task.failed_request_text ?? '')}
                >
                  {t('Restore unsent request')}
                </Button>
              )}
              {attachmentIds.length > 0 && (
                <AttachmentBadges
                  files={task.attachments.filter((file) =>
                    attachmentIds.includes(file.id),
                  )}
                  taskId={task.id}
                  t={t}
                  disabled={busy}
                  onRemove={(id) =>
                    setAttachmentIds((ids) =>
                      ids.filter((value) => value !== id),
                    )
                  }
                />
              )}
              {uploadStatus}
              <textarea
                aria-label={t('Describe your request')}
                placeholder={t('Describe your request')}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={3}
                maxLength={32000}
                onKeyDown={(event) => {
                  if (
                    event.key === 'Enter' &&
                    (event.metaKey || event.ctrlKey) &&
                    !event.nativeEvent.isComposing
                  )
                    event.currentTarget.form?.requestSubmit();
                }}
              />
              <div className="composer-toolbar">
                <div className="composer-controls">
                  <label className="mode-selector">
                    <span className="sr-only">{t('Execution mode')}</span>
                    <select
                      aria-label={t('Execution mode')}
                      disabled={busy || locked(task)}
                      value={
                        active(task)
                          ? task.stage === 'implement'
                            ? 'implement'
                            : 'plan'
                          : stage
                      }
                      onChange={(event) => {
                        setStage(event.target.value as typeof stage);
                      }}
                    >
                      <option value="plan">{t('Plan')}</option>
                      <option value="implement">{t('Execute')}</option>
                    </select>
                  </label>
                  <ExecutionSettings
                    models={models}
                    value={
                      active(task)
                        ? {
                            model: task.model ?? null,
                            effort: task.effort ?? null,
                            permissions:
                              task.permissions === 'yolo' ? 'yolo' : 'ask',
                          }
                        : selectedExecution
                    }
                    onChange={(next) =>
                      setExecution((current) => {
                        const modelChanged =
                          next.model !== selectedExecution.model;
                        return {
                          permissions: next.permissions,
                          model: modelChanged ? next.model : current.model,
                          effort: modelChanged
                            ? next.effort
                            : next.effort !== selectedExecution.effort
                              ? next.effort
                              : current.effort,
                        };
                      })
                    }
                    disabled={busy || locked(task)}
                    implementation={
                      active(task)
                        ? task.stage === 'implement'
                        : stage === 'implement'
                    }
                    error={modelsError}
                    onUpdateGuide={() => setUpdateGuideOpen(true)}
                    onRetry={() => selected && void refreshModels(selected)}
                    t={t}
                  />
                  {!!skills.length && (
                    <label className="skill-picker">
                      <span className="sr-only">{t('Use a skill')}</span>
                      <select
                        aria-label={t('Use a skill')}
                        disabled={busy || locked(task)}
                        value={skillNames[0] ?? ''}
                        onChange={(e) =>
                          setSkillNames(e.target.value ? [e.target.value] : [])
                        }
                      >
                        <option value="">{t('Use a skill')}</option>
                        {skills.map((skill) => (
                          <option
                            key={skill.name}
                            value={skill.name}
                            title={skill.description}
                          >
                            {skill.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                <div className="actions">
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={busy || task.status === 'uncertain'}
                    aria-label={t('Attach files')}
                    onClick={() => setAttachmentPicker(true)}
                  >
                    <Paperclip size={17} />
                  </Button>
                  {(running(task) ||
                    (task.status === 'uncertain' && task.thread_id)) && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() => void mutate('interrupt', {})}
                    >
                      <CircleStop size={15} />
                      {t('Stop')}
                    </Button>
                  )}
                  <Button
                    type="submit"
                    variant="primary"
                    disabled={
                      busy ||
                      (!message.trim() &&
                        (stage === 'implement' || !attachmentIds.length)) ||
                      task.status === 'starting'
                    }
                    aria-label={t(active(task) ? 'Add instruction' : 'Send')}
                  >
                    <ArrowUp size={17} />
                    {t(active(task) ? 'Add instruction' : 'Send')}
                  </Button>
                </div>
              </div>
              <p
                className={`composer-help ${
                  composerYolo
                    ? 'danger'
                    : composerPlanningHelp
                      ? ''
                      : 'layout-placeholder'
                }`}
                aria-hidden={!(composerYolo || composerPlanningHelp)}
              >
                {t(
                  composerYolo
                    ? 'YOLO runs commands without approval or sandbox restrictions.'
                    : 'Planning is read-only. Documents are updated only when requested or when agreed changes affect an existing document.',
                )}
              </p>
            </form>
          </section>
          <aside className="results" aria-label={t('Results')}>
            <nav className="result-tabs" aria-label={t('Results')}>
              {tabs.map((entry) => (
                <button
                  key={entry.id}
                  aria-pressed={tab === entry.id}
                  onClick={() => setTab(entry.id)}
                >
                  {t(entry.label)}
                </button>
              ))}
            </nav>
            {tab === 'plan' && (
              <Documents
                key={`${task.id}-${tab}`}
                task={task}
                draft={documentDrafts[`${task.id}:plan`] ?? null}
                onDraftChange={(next) => {
                  const key = `${task.id}:plan`;
                  setDocumentDrafts((current) => {
                    const draft =
                      typeof next === 'function'
                        ? next(current[key] ?? null)
                        : next;
                    const result = { ...current };
                    if (draft) result[key] = draft;
                    else delete result[key];
                    return result;
                  });
                }}
                t={t}
                busy={busy}
                onSave={(body) => mutate('documents', body, 'PUT')}
                onImplement={approveImplementation}
              />
            )}
            {tab === 'files' && uploadStatus}
            {tab === 'files' && (
              <FileLibrary
                task={task}
                selectedIds={attachmentIds}
                t={t}
                busy={busy}
                onToggle={toggleAttachment}
                onUpload={(files, select) => void uploadFiles(files, select)}
                onDelete={(id) =>
                  setFileToDelete(
                    task.attachments.find((file) => file.id === id) ?? null,
                  )
                }
              />
            )}
            {tab === 'branch' && (
              <GitWorkspace
                task={task}
                git={git}
                locale={locale}
                t={t}
                onError={onError}
              />
            )}
            {tab === 'checks' && (
              <div className="checks-pane">
                <p className="muted">
                  {t(
                    'Command results are execution evidence. Read the final response for tests run and checks skipped.',
                  )}
                </p>
                {task.items
                  .filter((item) => item.type === 'commandExecution')
                  .map((item, index) => (
                    <Command key={index} item={item} t={t} />
                  ))}
                {!task.items.some(
                  (item) => item.type === 'commandExecution',
                ) && (
                  <p className="empty-result">
                    {t('No commands have run yet.')}
                  </p>
                )}
              </div>
            )}
          </aside>
        </main>
      )}
      <Dialog
        open={newOpen}
        onOpenChange={setNewOpen}
        title={t('New task')}
        closeLabel={t('Close')}
      >
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            void act(async () => {
              const next = await api<Detail>('/tasks', {
                title,
                isolate,
              });
              await refreshTasks();
              choose(next.id);
              setNewOpen(false);
              setTitle('');
            });
          }}
        >
          <label htmlFor="task-title">{t('Task title')}</label>
          <Input
            id="task-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            maxLength={200}
            autoFocus
          />
          <label>
            <input
              type="checkbox"
              checked={isolate}
              onChange={(e) => setIsolate(e.target.checked)}
            />
            {t('Isolate this task for parallel work')}
          </label>
          <Button
            variant="primary"
            type="submit"
            disabled={busy || !title.trim()}
          >
            {t('Create task')}
          </Button>
        </form>
      </Dialog>
      <Confirm
        open={!!planToApprove}
        title="Execute the saved plan?"
        description="Codex may edit this checkout and run checks. The approved plan does not authorize publishing or deployment."
        action="Execute this plan"
        t={t}
        busy={busy}
        onClose={() => {
          setPlanToApprove(null);
        }}
        onConfirm={() => {
          if (!task || !planToApprove) return;
          const approvedTaskId = task.id;
          void send(
            'implement',
            {
              ...approvalExecution,
              text: approvalText,
              revision_id: planToApprove.id,
              attachment_ids: approvalFiles.map((file) => file.id),
            },
            approvedTaskId,
          ).then((ok) => {
            if (ok && selectedRef.current === approvedTaskId) {
              setPlanToApprove(null);
              setStage('implement');
              setExecution((current) => ({
                ...current,
                model: null,
                effort: null,
                permissions: approvalExecution.permissions,
              }));
              setMessage((current) =>
                current === approvalText ? '' : current,
              );
              setTab('branch');
            }
          });
        }}
      >
        {error && (
          <p role="alert" className="danger">
            {t(errorCopy(error))}
          </p>
        )}
        <p>
          {approvalDisplay.model ?? t('Loading model catalog…')}
          {approvalDisplay.effort ? ` · ${approvalDisplay.effort}` : ''}
        </p>
        <label className="stack">
          {t('Permissions')}
          <PermissionSelect
            value={approvalExecution.permissions}
            onChange={(permissions) =>
              setApprovalExecution((current) => ({ ...current, permissions }))
            }
            disabled={busy}
            t={t}
          />
        </label>
        {approvalExecution.permissions === 'yolo' && (
          <p className="danger">
            {t('YOLO runs commands without approval or sandbox restrictions.')}
          </p>
        )}
        {approvalText && <p className="confirmation-request">{approvalText}</p>}
        {task && approvalFiles.length > 0 && (
          <AttachmentBadges files={approvalFiles} taskId={task.id} t={t} />
        )}
      </Confirm>
      <Dialog
        open={attachmentPicker && !!task}
        onOpenChange={setAttachmentPicker}
        title={t('Attach files')}
        description={t('Only selected files are attached to this message.')}
        closeLabel={t('Close')}
      >
        {task && (
          <FileLibrary
            task={task}
            selectedIds={attachmentIds}
            t={t}
            busy={busy}
            selectUploads
            onToggle={toggleAttachment}
            onUpload={(files, select) => void uploadFiles(files, select)}
            onDelete={(id) =>
              setFileToDelete(
                task.attachments.find((file) => file.id === id) ?? null,
              )
            }
          />
        )}
        {uploadStatus}
        <Button onClick={() => setAttachmentPicker(false)}>{t('Done')}</Button>
      </Dialog>
      <Confirm
        open={!!fileToDelete}
        title="Delete file"
        description="The original will be deleted. Earlier conversation content is retained."
        action="Delete file"
        t={t}
        busy={busy}
        onClose={() => setFileToDelete(null)}
        onConfirm={() => {
          if (!fileToDelete) return;
          const id = fileToDelete.id;
          void mutate(`attachments/${id}`, undefined, 'DELETE').then((ok) => {
            if (ok) {
              setAttachmentIds((ids) => ids.filter((value) => value !== id));
              setFileToDelete(null);
            }
          });
        }}
      >
        <p>{fileToDelete?.name}</p>
      </Confirm>
      <Dialog
        open={!!importThread}
        onOpenChange={(open) => {
          if (!open) setImportThread(null);
        }}
        title={t('Resume conversation')}
        description={t('Confirm before resuming a CLI conversation.')}
        closeLabel={t('Close')}
      >
        <div className="stack">
          <p>{importThread?.title}</p>
          <label className="answer-option">
            <input
              type="checkbox"
              checked={confirmInactive}
              onChange={(event) => setConfirmInactive(event.target.checked)}
            />
            {t('The original CLI conversation is no longer running.')}
          </label>
          <Button
            variant="primary"
            disabled={!confirmInactive || busy}
            onClick={() =>
              void act(async () => {
                const next = await api<Detail>('/tasks/import', {
                  thread_id: importThread?.id,
                  confirm_inactive: true,
                });
                await refreshTasks();
                choose(next.id);
                setImportThread(null);
              })
            }
          >
            {t('Resume conversation')}
          </Button>
        </div>
      </Dialog>
      <CodexUpdateGuide
        open={updateGuideOpen}
        onOpenChange={setUpdateGuideOpen}
        locale={locale}
        t={t}
        openTemplates={() => navigate('templates')}
      />
      <Dialog
        open={usageOpen}
        onOpenChange={setUsageOpen}
        title={t('Usage')}
        closeLabel={t('Close')}
      >
        <div className="stack">
          <strong>
            {t(
              account?.auth_type === 'chatgpt'
                ? 'Subscription connected'
                : 'Codex unavailable',
            )}
          </strong>
          {account?.error_code && <p>{t(errorCopy(account.error_code))}</p>}
          {account?.plan_type && <p>{account.plan_type}</p>}
          {versionMismatch ? (
            <Button
              onClick={() => {
                setUsageOpen(false);
                setUpdateGuideOpen(true);
              }}
            >
              {t('Update instructions')}
            </Button>
          ) : account?.auth_type === 'chatgpt' ? (
            <Usage account={account} locale={locale} t={t} />
          ) : (
            <Button
              disabled={busy}
              onClick={() =>
                void act(async () =>
                  setDevice(await api<DeviceLogin>('/codex/login', {})),
                )
              }
            >
              {t('Connect ChatGPT')}
            </Button>
          )}
          {device && (
            <div className="stack">
              <p>{t('Enter this code on the sign-in page.')}</p>
              <code className="device-code">{device.user_code}</code>
              <a
                href={device.verification_url}
                target="_blank"
                rel="noreferrer"
              >
                {t('Open sign-in page')}
              </a>
            </div>
          )}
          <Button disabled={busy} onClick={() => void act(refreshAccount)}>
            <RefreshCw size={14} />
            {t('Refresh')}
          </Button>
        </div>
      </Dialog>
      {feedback}
    </div>
  );
}

function Usage({
  account,
  locale,
  t,
}: {
  account: Account;
  locale: Locale;
  t: ReturnType<typeof translate>;
}) {
  const limits = record(account.rate_limits);
  const rate = record(limits.rateLimits);
  const windows = [record(rate.primary), record(rate.secondary)].filter(
    (window) => typeof window.usedPercent === 'number',
  );
  if (!windows.length) return <p>{t('Usage is unavailable.')}</p>;
  return (
    <div className="stack">
      {windows.map((window, index) => (
        <div key={index} className="usage-window">
          <label>
            {t('Used')} {String(window.usedPercent)}%
            <progress max={100} value={Number(window.usedPercent)} />
          </label>
          {typeof window.resetsAt === 'number' && (
            <small>
              {t('Resets')} ·{' '}
              {new Date(window.resetsAt * 1000).toLocaleString(locale)}
            </small>
          )}
        </div>
      ))}
    </div>
  );
}
