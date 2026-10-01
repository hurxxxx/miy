import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { App } from './App';
import { api, ApiError, type Detail, type GitState } from './api';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
vi.mock('@pierre/diffs/react', () => ({ MultiFileDiff: () => <div /> }));

class Stream extends EventTarget {
  static current: Stream;
  constructor() {
    super();
    Stream.current = this;
  }
  close() {}
}

const taskId = '00000000-0000-4000-8000-000000000001';
let detail: Detail;
let gitState: GitState;
let submit: (body: Record<string, unknown>) => Promise<Detail>;
let recover: () => Promise<Detail>;
let searchTasks: (query: string) => Promise<Detail[]>;

beforeEach(() => {
  vi.stubGlobal('EventSource', Stream);
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  window.history.replaceState(null, '', `?task=${taskId}`);
  detail = {
    id: taskId,
    executor: 'session',
    title: 'Test task',
    stage: 'plan',
    status: 'idle',
    pinned: false,
    agents: [],
    pending_count: 0,
    permissions: 'read-only',
    thread_id: 'thread',
    turn_id: null,
    root: '/repo/dev',
    isolated: false,
    approved_revision: null,
    error_code: null,
    updated_at: '2026-09-19T00:00:00Z',
    event_id: 1,
    attachments: [],
    attachment_limits: {
      file_bytes: 52428800,
      task_bytes: 524288000,
      files: 200,
      selection: 20,
    },
    items: [],
    history_truncated: false,
    requests: [],
    revisions: [],
  };
  gitState = {
    root: '/repo/dev',
    branch: 'dev',
    head: 'a'.repeat(40),
    detached: false,
    upstream: 'origin/dev',
    ahead: 1,
    behind: 0,
    staged: 0,
    unstaged: 2,
    untracked: 1,
    conflicts: 0,
    changed: 3,
    checked_at: '2026-09-20T00:00:00Z',
  };
  submit = async () => detail;
  recover = async () => detail;
  searchTasks = async () => [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, body) => {
    if (path === '/session') return { authenticated: true };
    if (path === '/overview') return [detail];
    if (path === '/monitor/services') return [];
    if (path.startsWith('/overview?search=')) return searchTasks(path);
    if (path.startsWith('/codex/models?task_id='))
      return [
        {
          model: 'gpt-5.6-sol',
          name: 'GPT-5.6-Sol',
          is_default: false,
          default_effort: 'high',
          efforts: ['low', 'medium', 'high'],
        },
        {
          model: 'alternate',
          name: 'Alternate',
          is_default: true,
          default_effort: 'medium',
          efforts: ['low', 'medium', 'high'],
        },
      ];
    if (path === '/codex/account')
      return { connected: true, auth_type: 'chatgpt' };
    if (path === `/tasks/${taskId}`) return detail;
    if (path === `/tasks/${taskId}/git`) return gitState;
    if (path === `/tasks/${taskId}/implement`)
      return submit(body as Record<string, unknown>);
    if (path === `/tasks/${taskId}/messages`)
      return submit(body as Record<string, unknown>);
    if (path === `/tasks/${taskId}/recover`) return recover();
    if (path === `/tasks/${taskId}/interrupt`) return detail;
    throw new Error(`Unexpected test endpoint: ${path}`);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

it.each([false, true])(
  'keeps the newest overview state when an older response arrives late (latest failed: %s)',
  async (failed) => {
    render(<App />);
    await screen.findByRole('button', {
      name: /에이전트 활동.*실행 중 에이전트: 0/,
    });
    const original = vi.mocked(api).getMockImplementation()!;
    const requests: {
      resolve: (value: Detail[]) => void;
      reject: (error: Error) => void;
    }[] = [];
    vi.mocked(api).mockImplementation((path, ...args) =>
      path === '/overview'
        ? new Promise((resolve, reject) => {
            requests.push({ resolve, reject });
          })
        : original(path, ...args),
    );
    await act(async () => {
      Stream.current.dispatchEvent(new Event('changed'));
      Stream.current.dispatchEvent(new Event('changed'));
    });
    expect(requests).toHaveLength(2);
    await act(async () => {
      if (failed) requests[1].reject(new Error('offline'));
      else requests[1].resolve([{ ...detail, status: 'running' }]);
    });
    await act(async () => {
      requests[0].resolve([detail]);
    });
    expect(
      screen.getByRole('button', {
        name: failed
          ? /에이전트 활동.*상태 갱신 지연/
          : /에이전트 활동.*실행 중 에이전트: 1/,
      }),
    ).toBeTruthy();
  },
);

async function openAndCompose() {
  render(<App />);
  await screen.findByRole('heading', { name: 'Test task' });
  fireEvent.change(screen.getByLabelText('요청 내용 입력'), {
    target: { value: 'Same request' },
  });
}

it('shows the terminal repair prompt for model version failures and clears it after retry', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  let mismatch = true;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (mismatch && path.startsWith('/codex/models?task_id='))
      throw new ApiError('codex_version_mismatch');
    return original(path, ...args);
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  render(<App />);
  await screen.findByRole('button', { name: 'Codex 업데이트 필요' });
  expect(screen.queryByText('모델 목록 불러오는 중…')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '설정 변경' }));
  await screen.findByText(
    'Codex 버전 불일치로 콘솔 호환성 업데이트가 필요합니다.',
  );
  fireEvent.click(screen.getByRole('button', { name: '업데이트 안내' }));
  const dialog = screen.getByRole('dialog', { name: 'Codex 업데이트 필요' });
  const prompt = within(dialog).getByRole('textbox', {
    name: 'Codex CLI 업데이트 프롬프트',
  }) as HTMLTextAreaElement;
  expect(prompt.readOnly).toBe(true);
  expect(prompt.value).toContain('커밋');
  expect(prompt.value).toContain('GitLab origin에 푸시');
  expect(prompt.value).toContain('서비스 재시작');
  fireEvent.click(
    within(dialog).getByRole('button', { name: '프롬프트 복사' }),
  );
  await within(dialog).findByText('프롬프트를 복사했습니다.');
  expect(writeText).toHaveBeenCalledWith(prompt.value);
  fireEvent.click(within(dialog).getByRole('button', { name: '닫기' }));
  mismatch = false;
  fireEvent.click(
    screen.getByRole('button', { name: '모델 목록 다시 불러오기' }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText('모델')).toHaveProperty('disabled', false),
  );
  expect(
    screen.queryByRole('button', { name: 'Codex 업데이트 필요' }),
  ).toBeNull();
});

it('makes account version guidance available without a task and supports manual copying', async () => {
  window.history.replaceState(null, '', '/');
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path === '/overview') return [];
    if (path === '/codex/account')
      return { connected: false, error_code: 'codex_version_mismatch' };
    return original(path, ...args);
  });
  vi.stubGlobal('navigator', {
    clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
  });
  render(<App />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Codex 업데이트 필요' }),
  );
  fireEvent.click(screen.getByRole('button', { name: '프롬프트 복사' }));
  await screen.findByText('선택된 프롬프트를 직접 복사하세요.');
  const prompt = screen.getByRole('textbox', {
    name: 'Codex CLI 업데이트 프롬프트',
  }) as HTMLTextAreaElement;
  expect(prompt.selectionEnd).toBe(prompt.value.length);
  expect(prompt.selectionStart).toBe(0);
});

it('does not label other model failures as a version mismatch', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path.startsWith('/codex/models?task_id='))
      throw new ApiError('codex_unavailable');
    return original(path, ...args);
  });
  render(<App />);
  await screen.findByText('모델 목록을 불러오지 못했습니다.');
  expect(screen.queryByText('모델 목록 불러오는 중…')).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Codex 업데이트 필요' }),
  ).toBeNull();
});

it('retries an unavailable initial session check without a page reload', async () => {
  vi.mocked(api).mockRejectedValueOnce(new ApiError('request_failed'));
  render(<App />);
  const retry = await screen.findByRole('button', { name: '연결 다시 시도' });
  expect(
    (screen.getByRole('button', { name: '로그인' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(retry);
  await screen.findByRole('heading', { name: 'Test task' });
  expect(screen.queryByRole('button', { name: '연결 다시 시도' })).toBeNull();
});

it('exchanges an miy handoff before checking the existing session', async () => {
  const code = `cc1_${'a'.repeat(32)}`;
  window.history.replaceState(
    null,
    '',
    `/?task=${taskId}#${new URLSearchParams({
      miy_issuer: 'https://dev.example.test',
      miy_code: code,
    })}`,
  );
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path === '/session/miy') {
      expect(args[0]).toEqual({
        issuer: 'https://dev.example.test',
        code,
      });
      return { authenticated: true };
    }
    return original(path, ...args);
  });

  render(<App />);

  await screen.findByRole('heading', { name: 'Test task' });
  expect(window.location.hash).toBe('');
  expect(api).toHaveBeenCalledWith('/session/miy', {
    issuer: 'https://dev.example.test',
    code,
  });
  expect(api).not.toHaveBeenCalledWith('/session');
});

it('runs handoff initialization once when StrictMode replays effects', async () => {
  const code = `cc1_${'b'.repeat(32)}`;
  window.history.replaceState(
    null,
    '',
    `/?task=${taskId}#${new URLSearchParams({
      miy_issuer: 'https://dev.example.test',
      miy_code: code,
    })}`,
  );
  let finishHandoff!: (value: { authenticated: boolean }) => void;
  const handoff = new Promise<{ authenticated: boolean }>((resolve) => {
    finishHandoff = resolve;
  });
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path === '/session/miy') return handoff;
    return original(path, ...args);
  });

  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );

  await waitFor(() =>
    expect(
      vi.mocked(api).mock.calls.filter(([path]) => path === '/session/miy'),
    ).toHaveLength(1),
  );
  expect(api).not.toHaveBeenCalledWith('/session');
  await act(async () => finishHandoff({ authenticated: true }));
  await screen.findByRole('heading', { name: 'Test task' });
  expect(api).not.toHaveBeenCalledWith('/session');
});

it('preserves the plan draft across result tabs and tasks and warns before leaving the page', async () => {
  const other = {
    ...detail,
    id: '00000000-0000-4000-8000-000000000002',
    title: 'Another task',
  };
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) => {
    if (path === '/overview') return [detail, other];
    if (path === `/tasks/${other.id}`) return other;
    return original(path, ...args);
  });
  await openAndCompose();
  fireEvent.click(screen.getByRole('button', { name: '문서 편집' }));
  fireEvent.change(screen.getByRole('textbox', { name: '문서 편집' }), {
    target: { value: 'Plan draft' },
  });
  const results = within(screen.getByRole('navigation', { name: '결과물' }));
  fireEvent.click(results.getByRole('button', { name: '파일' }));
  fireEvent.click(results.getByRole('button', { name: '계획' }));
  expect(screen.getByText('Plan draft')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '에이전트' }));
  fireEvent.click(await screen.findByRole('button', { name: /Another task/ }));
  await screen.findByRole('heading', { name: 'Another task' });
  expect(screen.queryByText('Plan draft')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '에이전트' }));
  fireEvent.click(screen.getByRole('button', { name: /Test task/ }));
  await screen.findByText('Plan draft');
  fireEvent.click(
    within(screen.getByRole('navigation', { name: '결과물' })).getByRole(
      'button',
      { name: '계획' },
    ),
  );
  expect(screen.getByText('Plan draft')).toBeTruthy();
  const leaving = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(leaving);
  expect(leaving.defaultPrevented).toBe(true);
});

it('searches all tasks on the server without clearing the open draft or accepting stale results', async () => {
  let resolveOld!: (rows: Detail[]) => void;
  searchTasks = async (query) =>
    query.endsWith('old')
      ? new Promise((resolve) => {
          resolveOld = resolve;
        })
      : [{ ...detail, id: 'other', title: 'New search result' }];
  await openAndCompose();
  fireEvent.click(screen.getByRole('button', { name: '에이전트' }));
  fireEvent.change(screen.getByLabelText('작업 검색'), {
    target: { value: 'old' },
  });
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
  fireEvent.change(screen.getByLabelText('작업 검색'), {
    target: { value: 'new' },
  });
  await screen.findByRole('button', { name: /New search result/ });
  await act(async () =>
    resolveOld([{ ...detail, id: 'old', title: 'Old result' }]),
  );
  expect(screen.queryByRole('button', { name: /Old result/ })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '세션' }));
  fireEvent.click(
    within(screen.getByRole('list', { name: '세션' })).getByRole('button', {
      name: /Test task/,
    }),
  );
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('Same request');
});

it('offers explicit stop for an uncertain native thread without a saved turn ID', async () => {
  detail = {
    ...detail,
    status: 'uncertain',
    error_code: 'codex_request_uncertain',
  };
  render(<App />);
  const stop = await screen.findByRole('button', { name: '중단' });
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/interrupt')),
  ).toBe(false);
  fireEvent.click(stop);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/interrupt`,
      {},
      undefined,
    ),
  );
});

it('keeps a newer SSE result when an older submission response arrives last', async () => {
  let resolve!: (value: Detail) => void;
  submit = () =>
    new Promise((done) => {
      resolve = done;
    });
  await openAndCompose();
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expect(resolve).toBeTypeOf('function'));
  const older = { ...detail, status: 'running', event_id: 2 };
  detail = {
    ...detail,
    event_id: 3,
    items: [{ id: 'final', type: 'agentMessage', text: 'Completed result' }],
  };
  act(() => Stream.current.dispatchEvent(new Event('changed')));
  await screen.findByText('Completed result');
  await act(async () => resolve(older));
  expect(screen.getByText('Completed result')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('요청 내용 입력'), {
    target: { value: 'Next request' },
  });
  expect(
    (
      screen.getByRole('button', {
        name: '보내기',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});

it('retains retry identity on failed recovery and creates a new one only after successful explicit recovery', async () => {
  const attempts: string[] = [];
  submit = async (body) => {
    attempts.push(body.operation_id as string);
    detail = {
      ...detail,
      status: 'uncertain',
      error_code: 'codex_request_uncertain',
      event_id: detail.event_id + 1,
    };
    Stream.current.dispatchEvent(new Event('changed'));
    throw new ApiError('codex_request_uncertain');
  };
  recover = async () => {
    throw new ApiError('turn_not_finished');
  };
  await openAndCompose();
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await screen.findByRole('button', { name: '실행 상태 확인' });
  fireEvent.click(screen.getByRole('button', { name: '실행 상태 확인' }));
  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: '실행 상태 확인',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  // An ordinary state refresh does not authorize a new identity.
  detail = {
    ...detail,
    status: 'interrupted',
    error_code: null,
    event_id: detail.event_id + 1,
  };
  act(() => Stream.current.dispatchEvent(new Event('changed')));
  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: '보내기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expect(attempts).toHaveLength(2));
  expect(attempts[1]).toBe(attempts[0]);
  recover = async () => {
    detail = {
      ...detail,
      status: 'interrupted',
      error_code: null,
      event_id: detail.event_id + 1,
    };
    return detail;
  };
  fireEvent.click(
    await screen.findByRole('button', { name: '실행 상태 확인' }),
  );
  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: '보내기',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  expect(attempts).toHaveLength(2);
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('Same request');
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expect(attempts).toHaveLength(3));
  expect(attempts[2]).not.toBe(attempts[0]);
});

it('executes an explicit prompt with selected model and YOLO without requiring a document', async () => {
  await openAndCompose();
  fireEvent.click(await screen.findByRole('button', { name: '설정 변경' }));
  await screen.findByRole('option', { name: 'Alternate' });
  fireEvent.change(screen.getByLabelText('모델'), {
    target: { value: 'gpt-5.6-sol' },
  });
  fireEvent.change(screen.getByLabelText('추론 강도'), {
    target: { value: 'high' },
  });
  fireEvent.change(screen.getByLabelText('실행 모드'), {
    target: { value: 'implement' },
  });
  fireEvent.change(screen.getByLabelText('실행 권한'), {
    target: { value: 'yolo' },
  });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/implement`,
      expect.objectContaining({
        model: 'gpt-5.6-sol',
        effort: 'high',
        permissions: 'yolo',
        text: 'Same request',
      }),
    ),
  );
  const body = vi
    .mocked(api)
    .mock.calls.find(([path]) => path.endsWith('/implement'))![1];
  expect(body).not.toHaveProperty('revision_id');
});

it('shows a supported effort when the saved native effort is unavailable', async () => {
  detail = { ...detail, model: 'alternate', effort: 'max' };
  await openAndCompose();
  fireEvent.click(await screen.findByRole('button', { name: '설정 변경' }));
  await screen.findByRole('option', { name: 'Alternate' });
  expect((screen.getByLabelText('추론 강도') as HTMLSelectElement).value).toBe(
    'medium',
  );
  expect(screen.queryByRole('option', { name: 'max' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/messages`,
      expect.objectContaining({ model: null, effort: null }),
    ),
  );
});

it('shows the Codex catalog default without overriding the native thread', async () => {
  await openAndCompose();
  expect(await screen.findByText('Alternate · medium')).toBeTruthy();
  expect(screen.queryByText('Codex 기본 설정')).toBeNull();
  expect(screen.queryByText('기본값')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/messages`,
      expect.objectContaining({
        model: null,
        effort: null,
      }),
    ),
  );
});

it('does not override the native model when only permissions change', async () => {
  await openAndCompose();
  fireEvent.change(screen.getByLabelText('실행 모드'), {
    target: { value: 'implement' },
  });
  fireEvent.change(screen.getByLabelText('실행 권한'), {
    target: { value: 'yolo' },
  });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/implement`,
      expect.objectContaining({
        model: null,
        effort: null,
        permissions: 'yolo',
      }),
    ),
  );
});

it('uses the first available model when Codex marks no catalog default', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) =>
    path.startsWith('/codex/models?task_id=')
      ? [
          {
            model: 'alternate',
            name: 'Alternate',
            is_default: false,
            default_effort: 'medium',
            efforts: ['low', 'medium', 'high'],
          },
        ]
      : original(path, ...args),
  );
  await openAndCompose();
  expect(await screen.findByText('Alternate · medium')).toBeTruthy();
});

it('lets Codex retain a user-selected model for later turns', async () => {
  submit = async (body) => {
    detail = {
      ...detail,
      model: (body.model as string | null) ?? detail.model ?? 'alternate',
      effort: (body.effort as string | null) ?? detail.effort ?? 'medium',
      event_id: detail.event_id + 1,
    };
    return detail;
  };
  await openAndCompose();
  fireEvent.click(await screen.findByRole('button', { name: '설정 변경' }));
  await screen.findByRole('option', { name: 'GPT-5.6-Sol' });
  fireEvent.change(screen.getByLabelText('모델'), {
    target: { value: 'gpt-5.6-sol' },
  });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/messages`,
      expect.objectContaining({ model: 'gpt-5.6-sol', effort: 'high' }),
    ),
  );
  await screen.findByText('GPT-5.6-Sol · high');
  fireEvent.change(screen.getByLabelText('요청 내용 입력'), {
    target: { value: 'Next request' },
  });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/messages`,
      expect.objectContaining({
        text: 'Next request',
        model: null,
        effort: null,
      }),
    ),
  );
});

it('allows an explicit continuation prompt after interruption without a dedicated resume button', async () => {
  detail = {
    ...detail,
    stage: 'implement',
    status: 'uncertain',
    permissions: 'ask',
  };
  await openAndCompose();
  expect(
    screen.queryByRole('button', { name: '중단 지점부터 계속' }),
  ).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/tasks/${taskId}/implement`,
      expect.objectContaining({ text: 'Same request' }),
    ),
  );
});

it('shows native progress and keeps execution settings fixed while steering', async () => {
  detail = {
    ...detail,
    stage: 'implement',
    status: 'running',
    permissions: 'yolo',
    model: 'alternate',
    progress: {
      steps: [
        { step: 'Inspect source', status: 'completed' },
        { step: 'Check gameplay', status: 'inProgress' },
      ],
    },
  };
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) =>
    path.endsWith('/steer') ? detail : original(path, ...args),
  );
  await openAndCompose();
  expect(screen.getByText('Inspect source')).toBeTruthy();
  expect(screen.getByText('Check gameplay')).toBeTruthy();
  const progress = screen
    .getByText('Inspect source')
    .closest('details') as HTMLDetailsElement | null;
  expect(progress?.open).toBe(false);
  expect(
    screen
      .getByText('YOLO는 승인 요청과 샌드박스 제한 없이 명령을 실행합니다.')
      .closest('.composer-help'),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText('실행 모드') as HTMLSelectElement).disabled,
  ).toBe(true);
  expect(
    (screen.getByRole('button', { name: '설정 변경' }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: '보충 지시 보내기' }));
  await waitFor(() =>
    expect(
      vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/steer')),
    ).toBe(true),
  );
  const request = vi
    .mocked(api)
    .mock.calls.find(([path]) => path.endsWith('/steer'))![1] as Record<
    string,
    unknown
  >;
  expect(request.text).toBe('Same request');
  expect(request).not.toHaveProperty('model');
  expect(request).not.toHaveProperty('stage');
});

it('uses planning by default without saving a document from the browser', async () => {
  await openAndCompose();
  expect((screen.getByLabelText('실행 모드') as HTMLSelectElement).value).toBe(
    'plan',
  );
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() =>
    expect(
      vi
        .mocked(api)
        .mock.calls.some(
          ([path, body]) =>
            path.endsWith('/messages') &&
            (body as Record<string, unknown>).stage === 'plan',
        ),
    ).toBe(true),
  );
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/documents')),
  ).toBe(false);
});

it('shows the actual branch and changes in a read-only branch tab without merge targets', async () => {
  gitState.branch = null;
  gitState.detached = true;
  gitState.upstream = null;
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, ...args) =>
    path.endsWith('/changes') ? [] : original(path, ...args),
  );
  await openAndCompose();
  await screen.findByText('브랜치 없음 (detached HEAD)');
  expect(screen.queryByRole('button', { name: '병합 요청' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '브랜치' }));
  await screen.findByText('/repo/dev');
  expect(screen.queryByLabelText('대상 브랜치')).toBeNull();
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('Same request');
  expect(
    within(screen.getByLabelText('실행 모드'))
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual(['계획', '실행']);
});

it('restores a request rejected before execution without automatically sending it', async () => {
  detail.status = 'failed';
  detail.error_code = 'sandbox_policy_mismatch';
  detail.failed_request_text = 'An unsent ordinary question';
  render(<App />);
  fireEvent.click(
    await screen.findByRole('button', { name: '전송하지 못한 요청 불러오기' }),
  );
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('An unsent ordinary question');
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/messages')),
  ).toBe(false);
});

it('opens the sessions menu by pinned/recency order, preserves drafts and never starts work when switching', async () => {
  const second = {
    ...detail,
    id: '00000000-0000-4000-8000-000000000002',
    title: 'Pinned earlier session',
    pinned: true,
    updated_at: '2026-09-01T00:00:00Z',
  };
  const third = {
    ...detail,
    id: '00000000-0000-4000-8000-000000000003',
    title: 'Older active session',
    status: 'running',
    updated_at: '2026-09-02T00:00:00Z',
  };
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, ...args) => {
    if (path === '/overview') return Promise.resolve([third, detail, second]);
    if (path === `/tasks/${second.id}`) return Promise.resolve(second);
    if (path === `/tasks/${second.id}/git`) return Promise.resolve(gitState);
    if (path === `/tasks/${second.id}/skills`) return Promise.resolve([]);
    return original(path, ...args);
  });
  await openAndCompose();
  expect(screen.queryByRole('list', { name: '최근 세션' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '세션 목록으로' }));
  const sessions = () => within(screen.getByRole('list', { name: '세션' }));
  expect(
    sessions()
      .getAllByRole('button')
      .map((b) => b.querySelector('.session-title')?.textContent),
  ).toEqual([
    '고정됨Pinned earlier session',
    'Test task',
    'Older active session',
  ]);
  expect(
    sessions()
      .getByRole('button', { name: /Test task/ })
      .getAttribute('aria-current'),
  ).toBe('true');
  fireEvent.click(
    sessions().getByRole('button', { name: /Pinned earlier session/ }),
  );
  await screen.findByRole('heading', { name: second.title });
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('');
  fireEvent.click(screen.getByRole('button', { name: '세션 목록으로' }));
  fireEvent.click(sessions().getByRole('button', { name: /Test task/ }));
  await screen.findByRole('heading', { name: detail.title });
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('Same request');
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(
        ([path, body]) => body || /\/(plan|implement|import)$/.test(path),
      ),
  ).toHaveLength(0);
});

it('searches older sessions, rejects stale responses and keeps search when returning from work', async () => {
  let resolveOld!: (rows: Detail[]) => void;
  let fail = true;
  searchTasks = async (query) => {
    if (query.endsWith('old'))
      return new Promise((resolve) => {
        resolveOld = resolve;
      });
    if (fail) throw new Error('offline');
    return [detail];
  };
  await openAndCompose();
  fireEvent.click(screen.getByRole('button', { name: '세션 목록으로' }));
  fireEvent.change(screen.getByLabelText('세션 검색'), {
    target: { value: 'old' },
  });
  await waitFor(() => expect(resolveOld).toBeTypeOf('function'));
  fireEvent.change(screen.getByLabelText('세션 검색'), {
    target: { value: 'matching' },
  });
  await screen.findByText(
    '세션 목록을 갱신하지 못했습니다. 마지막으로 받은 목록을 표시합니다.',
  );
  expect(screen.queryByText('검색한 세션이 없습니다')).toBeNull();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await screen.findByRole('button', { name: /Test task/ });
  await act(async () => resolveOld([{ ...detail, title: 'Stale result' }]));
  expect(screen.queryByRole('button', { name: /Stale result/ })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: /Test task/ }));
  expect(
    (screen.getByLabelText('요청 내용 입력') as HTMLTextAreaElement).value,
  ).toBe('Same request');
  fireEvent.click(screen.getByRole('button', { name: '세션 목록으로' }));
  expect((screen.getByLabelText('세션 검색') as HTMLInputElement).value).toBe(
    'matching',
  );
});

it.each(['', '?view=sessions', '?view=workspace&tab=sessions'])(
  'opens the session list as the entry point at %s',
  async (route) => {
    window.history.replaceState(null, '', route || '/');
    render(<App />);
    await screen.findByRole('heading', { name: '세션' });
    expect(
      within(screen.getByRole('navigation', { name: '콘솔 메뉴' }))
        .getAllByRole('button')
        .map((b) => b.textContent),
    ).toEqual(['세션', '작업 템플릿', '에이전트', '모니터링']);
    expect(screen.queryByRole('list', { name: '최근 세션' })).toBeNull();
  },
);

it('keeps legacy native-session links under workspace and retains explicit import confirmation', async () => {
  window.history.replaceState(null, '', '?view=agents&tab=codex');
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, ...args) =>
    path.startsWith('/codex/threads')
      ? Promise.resolve({
          items: [
            { id: 'native-thread', title: 'CLI conversation', updated_at: 1 },
          ],
          cursor: null,
        })
      : original(path, ...args),
  );
  render(<App />);
  await screen.findByRole('heading', { name: 'Codex 세션 불러오기' });
  expect(
    within(screen.getByRole('navigation', { name: '콘솔 메뉴' }))
      .getByRole('button', { name: '세션' })
      .getAttribute('aria-current'),
  ).toBe('page');
  fireEvent.click(
    await screen.findByRole('button', { name: /CLI conversation/ }),
  );
  const dialog = within(screen.getByRole('dialog'));
  expect(
    dialog
      .getByRole('button', { name: '대화 이어가기' })
      .hasAttribute('disabled'),
  ).toBe(true);
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path === '/tasks/import'),
  ).toBe(false);
});
