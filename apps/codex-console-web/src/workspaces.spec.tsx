import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError, type Task } from './api';
import { translate } from './i18n';
import {
  ProjectWorkspaces,
  WorkspacePanel,
  type Workspace,
} from './workspaces';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
const project = {
  id: 'de7a6d7d-5f69-4901-ab18-841ddc54f1db',
  app_id: 'equipment',
  title: 'Equipment work',
  summary: 'Track equipment loans.',
  reuse_decision: 'new' as const,
  reuse_notes: 'Review current capabilities.',
  created_at: '2026-10-11T00:00:00Z',
};
const source = 'a'.repeat(40);
const runtime = 'b'.repeat(40);
function environment(change: Partial<Workspace> = {}): Workspace {
  return {
    id: 'c5f06e0a-d33c-42d4-90c5-a465027f0471',
    project_id: project.id,
    app_id: project.app_id,
    title: 'Equipment change',
    profile: 'app',
    state: 'ready',
    version: 3,
    admission_open: true,
    auto_refresh: true,
    branch: 'feature/wb-equipment-c5f06e0a',
    base_revision: runtime,
    source_revision: source,
    preview: {
      state: 'ready',
      portal_url:
        'https://dev.example.test/apps/equipment?installation_id=preview-1',
      installation_id: 'preview-1',
      source_revision: source,
      runtime_revision: source,
      failure_code: null,
    },
    integration: {
      state: 'not_requested',
      mr_url: null,
      mr_id: null,
      source_revision: null,
      merged_revision: null,
      dev_runtime_revision: null,
      failure_code: null,
    },
    cleanup: { state: 'not_requested', failure_code: null },
    failure_code: null,
    operations: [],
    created_at: project.created_at,
    updated_at: project.created_at,
    ...change,
  };
}
const props = () => ({
  t: translate('en-US'),
  tasks: [] as Task[],
  openTask: vi.fn(),
  startTask: vi.fn().mockResolvedValue(undefined),
});
beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, '', '/?view=studio');
});

function waitingReview(): Workspace {
  return environment({
    admission_open: true,
    integration: {
      ...environment().integration,
      state: 'reviewing',
      source_revision: source,
      mr_id: 7,
      mr_url: 'https://git.example.test/team/miy/-/merge_requests/7',
    },
    operations: [
      {
        operation_id: '0882f809-1726-4008-968f-1c706b49e8c7',
        kind: 'integrate',
        state: 'waiting',
        source_revision: source,
        failure_code: null,
        retryable: false,
        continuable: true,
        unknown: false,
        created_at: project.created_at,
        updated_at: project.created_at,
      },
    ],
  });
}

it('stops then resumes MR review waiting and explicitly continues the same review identity', async () => {
  const workspace = waitingReview();
  const reviewId = workspace.operations[0].operation_id;
  let current = workspace;
  vi.mocked(api).mockImplementation(async (path, body) => {
    if (!body) return current as never;
    const intent = body as { operation_id: string; expected_version: number };
    expect(intent.expected_version).toBe(current.version);
    if (path.endsWith('/stop') || path.endsWith('/resume')) {
      const stopping = path.endsWith('/stop');
      expect(intent.operation_id).not.toBe(reviewId);
      current = {
        ...current,
        version: current.version + 2,
        state: stopping ? 'stopped' : 'ready',
        admission_open: !stopping,
        preview: {
          ...current.preview,
          state: stopping ? 'stopped' : 'configured',
        },
        operations: [
          {
            ...workspace.operations[0],
            operation_id: intent.operation_id,
            kind: stopping ? 'stop' : 'resume',
            state: 'succeeded',
            continuable: false,
          },
          ...current.operations,
        ],
      };
    } else {
      expect(path).toBe(`/workbench/workspaces/${workspace.id}/integrate`);
      expect(current.state).toBe('ready');
      expect(intent.operation_id).toBe(reviewId);
      current = { ...current, version: current.version + 2 };
    }
    return current as never;
  });
  render(<WorkspacePanel id={workspace.id} {...props()} />);
  const stop = await screen.findByRole('button', { name: 'Stop environment' });
  expect((stop as HTMLButtonElement).disabled).toBe(false);
  expect(
    (
      screen.getByRole('button', {
        name: 'Continue operation',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  for (const name of [
    'Refresh app build',
    'Apply to development',
    'Clean up environment',
  ])
    expect(
      (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
    ).toBe(true);
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    0,
  );
  fireEvent.click(stop);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/workbench/workspaces/${workspace.id}/stop`,
      {
        operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
        expected_version: workspace.version,
      },
      'POST',
      expect.any(AbortSignal),
    ),
  );
  const posts = vi.mocked(api).mock.calls.filter(([, body]) => !!body);
  expect(posts).toHaveLength(1);
  expect((posts[0][1] as { operation_id: string }).operation_id).not.toBe(
    workspace.operations[0].operation_id,
  );
  expect(posts[0][0]).not.toMatch(/\/(integrate|refresh|cleanup)$/);
  const resume = screen.getByRole('button', { name: 'Resume environment' });
  await waitFor(() =>
    expect((resume as HTMLButtonElement).disabled).toBe(false),
  );
  const continuation = screen.getByRole('button', {
    name: 'Continue operation',
  });
  expect((continuation as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(continuation);
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    1,
  );
  fireEvent.click(resume);
  await waitFor(() =>
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
      2,
    ),
  );
  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: 'Continue operation',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Continue operation' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/workbench/workspaces/${workspace.id}/integrate`,
      { operation_id: reviewId, expected_version: workspace.version + 4 },
      'POST',
      expect.any(AbortSignal),
    ),
  );
  const finalPosts = vi.mocked(api).mock.calls.filter(([, body]) => !!body);
  expect(finalPosts.map(([path]) => path.split('/').at(-1))).toEqual([
    'stop',
    'resume',
    'integrate',
  ]);
  expect(
    new Set(
      finalPosts
        .slice(0, 2)
        .map(([, body]) => (body as { operation_id: string }).operation_id),
    ).size,
  ).toBe(2);
  expect(current.integration).toEqual(workspace.integration);
  expect(current.source_revision).toBe(workspace.source_revision);
  expect(current.operations.find((op) => op.operation_id === reviewId)).toEqual(
    workspace.operations[0],
  );
});

it.each(
  ['ready', 'stopped'].flatMap((environmentState) =>
    ['pending', 'running', 'unknown', 'uncertain_flag'].map((state) => [
      environmentState,
      state,
    ]),
  ),
)(
  'keeps stop/resume and review continuation blocked in %s when an unresolved operation is %s',
  async (environmentState, state) => {
    const workspace = waitingReview();
    workspace.state = environmentState;
    workspace.operations.push({
      ...workspace.operations[0],
      operation_id: 'd121394c-e8ec-400e-b32c-e0497a12e488',
      kind: 'refresh',
      state: state === 'uncertain_flag' ? 'waiting' : state,
      unknown: state === 'uncertain_flag',
    });
    vi.mocked(api).mockResolvedValue(workspace as never);
    render(<WorkspacePanel id={workspace.id} {...props()} />);
    const stop = await screen.findByRole('button', {
      name: 'Stop environment',
    });
    const continuation = screen.getByRole('button', {
      name: 'Continue operation',
    });
    const resume = screen.getByRole('button', { name: 'Resume environment' });
    expect((stop as HTMLButtonElement).disabled).toBe(true);
    expect((resume as HTMLButtonElement).disabled).toBe(true);
    expect((continuation as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(stop);
    fireEvent.click(resume);
    fireEvent.click(continuation);
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
      0,
    );
  },
);

it.each(
  ['ready', 'stopped'].flatMap((environmentState) =>
    ['other_action', 'integration_merged', 'other_review_source'].map(
      (boundary) => [environmentState, boundary],
    ),
  ),
)(
  'does not treat waiting %s/%s as the current source MR review lifecycle exception',
  async (environmentState, boundary) => {
    const workspace = waitingReview();
    workspace.state = environmentState;
    if (boundary === 'other_action') workspace.operations[0].kind = 'refresh';
    else if (boundary === 'integration_merged')
      workspace.integration.state = 'merged';
    else workspace.integration.source_revision = runtime;
    vi.mocked(api).mockResolvedValue(workspace as never);
    render(<WorkspacePanel id={workspace.id} {...props()} />);
    const stop = await screen.findByRole('button', {
      name: 'Stop environment',
    });
    expect((stop as HTMLButtonElement).disabled).toBe(true);
    const resume = screen.getByRole('button', { name: 'Resume environment' });
    expect((resume as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(stop);
    fireEvent.click(resume);
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
      0,
    );
  },
);

it('does not retry a review-waiting resume after its response is lost', async () => {
  const workspace = waitingReview();
  workspace.state = 'stopped';
  workspace.admission_open = false;
  vi.mocked(api).mockImplementation(async (_, body) => {
    if (body) throw new ApiError('request_failed');
    return workspace as never;
  });
  render(<WorkspacePanel id={workspace.id} {...props()} />);
  const resume = await screen.findByRole('button', {
    name: 'Resume environment',
  });
  expect((resume as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(resume);
  await screen.findByText(
    'The response was lost. Check the existing operation before requesting another action.',
  );
  for (const name of [
    'Resume environment',
    'Stop environment',
    'Continue operation',
  ]) {
    const button = screen.getByRole('button', { name });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
  }
  const posts = vi.mocked(api).mock.calls.filter(([, body]) => !!body);
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe(`/workbench/workspaces/${workspace.id}/resume`);
  expect(workspace.operations[0].state).toBe('waiting');
});

it.each(['not_requested', 'reviewing', 'merged'])(
  'disables cleanup before verified development delivery (%s) without blocking development',
  async (state) => {
    const workspace = environment({
      integration: { ...environment().integration, state },
    });
    vi.mocked(api).mockResolvedValue(workspace as never);
    render(<WorkspacePanel id={workspace.id} project={project} {...props()} />);
    const cleanup = await screen.findByRole('button', {
      name: 'Clean up environment',
    });
    expect(cleanup.hasAttribute('disabled')).toBe(true);
    expect(
      screen
        .getByRole('button', { name: 'Start a development session' })
        .hasAttribute('disabled'),
    ).toBe(false);
    fireEvent.click(cleanup);
    expect(
      screen.queryByRole('region', { name: 'Confirm development action' }),
    ).toBeNull();
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toEqual([]);
  },
);

it('allows explicit cleanup continuation only after verified development delivery', async () => {
  const workspace = environment({
    state: 'cleanup_pending',
    admission_open: false,
    integration: {
      ...environment().integration,
      state: 'succeeded',
      source_revision: source,
      merged_revision: runtime,
      dev_runtime_revision: runtime,
    },
  });
  vi.mocked(api).mockResolvedValue(workspace as never);
  render(<WorkspacePanel id={workspace.id} project={project} {...props()} />);
  const cleanup = await screen.findByRole('button', {
    name: 'Clean up environment',
  });
  expect(cleanup.hasAttribute('disabled')).toBe(false);
  fireEvent.click(cleanup);
  fireEvent.click(
    within(
      screen.getByRole('region', { name: 'Confirm development action' }),
    ).getByRole('button', { name: 'Clean up environment' }),
  );
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/workbench/workspaces/${workspace.id}/cleanup`,
      {
        operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
        expected_version: workspace.version,
      },
      'POST',
      expect.any(AbortSignal),
    ),
  );
});

it('selects a durable environment and starts another session there without creating another workspace or embedding the app', async () => {
  const first = environment();
  const second = environment({
    id: 'c498722f-a873-4ef8-b38f-6dca030c125e',
    title: 'Equipment second change',
    branch: 'feature/wb-equipment-c498722f',
  });
  vi.mocked(api).mockImplementation(async (path) => {
    if (path.endsWith('/workspaces'))
      return { available: true, items: [first, second] } as never;
    return (path.endsWith(second.id) ? second : first) as never;
  });
  const handlers = props();
  const { container } = render(
    <ProjectWorkspaces project={project} {...handlers} />,
  );
  fireEvent.change(
    await screen.findByLabelText('Choose a development environment'),
    { target: { value: second.id } },
  );
  expect(await screen.findByText(second.branch)).not.toBeNull();
  fireEvent.click(
    screen.getByRole('button', { name: 'Start a development session' }),
  );
  await waitFor(() =>
    expect(handlers.startTask).toHaveBeenCalledWith(
      expect.objectContaining({
        app_id: 'equipment',
        project_id: project.id,
        workspace_id: second.id,
        purpose: 'development',
      }),
      project.title,
      expect.stringContaining('selected managed development environment'),
    ),
  );
  const link = screen.getByRole('link', { name: 'Open app in new tab' });
  expect(link.getAttribute('href')).toBe(second.preview.portal_url);
  expect(link.getAttribute('target')).toBe('_blank');
  expect(link.getAttribute('rel')).toContain('noopener');
  expect(container.querySelector('iframe')).toBeNull();
  expect(api).not.toHaveBeenCalledWith(
    expect.anything(),
    expect.anything(),
    'POST',
    expect.anything(),
  );
  expect(new URLSearchParams(window.location.search).get('environment')).toBe(
    second.id,
  );
});

it('prepares managed MIY source without repository or root inputs and waits for readiness before a session', async () => {
  let created = false;
  const preparing = environment({
    state: 'preparing',
    admission_open: false,
    preview: {
      ...environment().preview,
      state: 'pending',
      portal_url: null,
      runtime_revision: null,
    },
  });
  vi.mocked(api).mockImplementation(async (path, body) => {
    if (body) {
      created = true;
      return preparing as never;
    }
    if (path.endsWith('/workspaces'))
      return { available: true, items: created ? [preparing] : [] } as never;
    return preparing as never;
  });
  const handlers = props();
  render(<ProjectWorkspaces project={project} {...handlers} />);
  await screen.findByText('No development environments yet.');
  fireEvent.click(
    screen.getByRole('button', { name: 'New development environment' }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Prepare environment' }));
  await screen.findByText('Environment preparing');
  const posts = vi.mocked(api).mock.calls.filter(([, body]) => !!body);
  expect(posts).toHaveLength(1);
  expect(posts[0][1]).toEqual({
    operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
    title: project.title,
    profile: 'app',
    auto_refresh: true,
  });
  expect(screen.queryByLabelText('Repository')).toBeNull();
  expect(
    screen
      .getByRole('button', { name: 'Start a development session' })
      .hasAttribute('disabled'),
  ).toBe(true);
  expect(handlers.startTask).not.toHaveBeenCalled();
  expect(
    screen.queryByRole('link', { name: 'Open app in new tab' }),
  ).toBeNull();
});

it('keeps initial registration on the ready workspace even before an app runtime is configured', async () => {
  const workspace = environment({
    preview: {
      ...environment().preview,
      state: 'unconfigured',
      portal_url: null,
      runtime_revision: null,
    },
  });
  vi.mocked(api).mockResolvedValue(workspace as never);
  const handlers = props();
  render(<WorkspacePanel id={workspace.id} project={project} {...handlers} />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'New registration task' }),
  );
  await waitFor(() =>
    expect(handlers.startTask).toHaveBeenCalledWith(
      expect.objectContaining({
        purpose: 'registration',
        workspace_id: workspace.id,
        project_id: project.id,
        app_id: project.app_id,
      }),
      project.title,
      expect.stringContaining(
        'MIY owner authorization and explicit implementation approval',
      ),
    ),
  );
  expect(
    screen.queryByRole('link', { name: 'Open app in new tab' }),
  ).toBeNull();
});

it.each([
  ['integrate', 'integrate'],
  ['auto_refresh', 'refresh'],
])(
  'continues a recorded waiting action %s only on explicit request with the same operation identity',
  async (kind, action) => {
    const operation = {
      operation_id: '0882f809-1726-4008-968f-1c706b49e8c7',
      kind,
      state: 'waiting',
      source_revision: source,
      failure_code: null,
      retryable: false,
      continuable: true,
      unknown: false,
      created_at: project.created_at,
      updated_at: project.created_at,
    };
    const current = environment({
      version: 8,
      operations: [operation],
      integration: { ...environment().integration, state: 'reviewing' },
    });
    vi.mocked(api).mockResolvedValue(current as never);
    render(<WorkspacePanel id={current.id} {...props()} />);
    const continuation = await screen.findByRole('button', {
      name: 'Continue operation',
    });
    expect(
      (
        screen.getByRole('button', {
          name: 'Apply to development',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
      0,
    );
    fireEvent.click(continuation);
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        `/workbench/workspaces/${current.id}/${action}`,
        { operation_id: operation.operation_id, expected_version: 8 },
        'POST',
        expect.any(AbortSignal),
      ),
    );
  },
);

it('shows a stale running revision and requires an explicit build refresh', async () => {
  const current = environment({
    preview: { ...environment().preview, runtime_revision: runtime },
  });
  vi.mocked(api).mockResolvedValue(current as never);
  render(<WorkspacePanel id={current.id} {...props()} />);
  await screen.findByText(
    'Saved changes are not running yet. Refresh the app build after finishing your changes.',
  );
  expect(api).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh app build' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/workbench/workspaces/${current.id}/refresh`,
      { operation_id: expect.any(String), expected_version: 3 },
      'POST',
      expect.any(AbortSignal),
    ),
  );
});

it('allows a new explicit action after the source changes while retaining the old waiting history', async () => {
  const oldOperation = {
    operation_id: '0882f809-1726-4008-968f-1c706b49e8c7',
    kind: 'integrate',
    state: 'waiting',
    source_revision: runtime,
    failure_code: null,
    retryable: false,
    continuable: false,
    unknown: false,
    created_at: project.created_at,
    updated_at: project.created_at,
  };
  const current = environment({ operations: [oldOperation] });
  vi.mocked(api).mockResolvedValue(current as never);
  render(<WorkspacePanel id={current.id} {...props()} />);
  await screen.findByText(
    'The source has changed. Start a new action to use the current version.',
  );
  expect(
    screen.queryByRole('button', { name: 'Continue operation' }),
  ).toBeNull();
  for (const name of [
    'Refresh app build',
    'Apply to development',
    'Stop environment',
  ])
    expect(
      (screen.getByRole('button', { name }) as HTMLButtonElement).disabled,
    ).toBe(false);
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    0,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Refresh app build' }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/workbench/workspaces/${current.id}/refresh`,
      { operation_id: expect.any(String), expected_version: current.version },
      'POST',
      expect.any(AbortSignal),
    ),
  );
  const submitted = vi.mocked(api).mock.calls.find(([, body]) => !!body)?.[1];
  expect((submitted as { operation_id: string }).operation_id).not.toBe(
    oldOperation.operation_id,
  );
});

it('does not replay an uncertain mutation; an explicit read finds the recorded failure before a new user request', async () => {
  let operationId = '';
  let observed = false;
  const current = environment();
  vi.mocked(api).mockImplementation(async (path, body) => {
    if (body) {
      operationId = (body as { operation_id: string }).operation_id;
      if (!observed) throw new ApiError('request_failed');
      return current as never;
    }
    if (!operationId) return current as never;
    observed = true;
    return {
      ...current,
      operations: [
        {
          operation_id: operationId,
          kind: 'refresh',
          state: 'failed',
          source_revision: source,
          failure_code: 'workspace_runtime_unavailable',
          retryable: true,
          unknown: false,
          created_at: project.created_at,
          updated_at: project.created_at,
        },
      ],
    } as never;
  });
  render(<WorkspacePanel id={current.id} {...props()} />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Refresh app build' }),
  );
  await screen.findByText(
    'The response was lost. Check the existing operation before requesting another action.',
  );
  const stop = screen.getByRole('button', { name: 'Stop environment' });
  expect((stop as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(stop);
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    1,
  );
  expect(
    screen
      .getByRole('button', { name: 'Refresh app build' })
      .hasAttribute('disabled'),
  ).toBe(true);
  const oldId = operationId;
  fireEvent.click(
    screen.getByRole('button', { name: 'Check operation state' }),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: 'Refresh app build' })
        .hasAttribute('disabled'),
    ).toBe(false),
  );
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    1,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Refresh app build' }));
  await waitFor(() =>
    expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
      2,
    ),
  );
  expect(operationId).not.toBe(oldId);
});

it('separates merge from actual dev execution and cleanup, and confirms the bounded integration intent', async () => {
  const initial = environment();
  const merged = environment({
    version: 4,
    integration: {
      ...initial.integration,
      state: 'completed',
      mr_url: 'https://gitlab.example.test/miy/merge_requests/8',
      merged_revision: runtime,
      dev_runtime_revision: null,
    },
  });
  vi.mocked(api).mockImplementation(
    async (_path, body) => (body ? merged : initial) as never,
  );
  render(<WorkspacePanel id={initial.id} {...props()} />);
  fireEvent.click(
    await screen.findByRole('button', { name: 'Apply to development' }),
  );
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    0,
  );
  const confirmation = screen.getByRole('region', {
    name: 'Confirm development action',
  });
  expect(
    within(confirmation).getByText(/development app update/),
  ).not.toBeNull();
  fireEvent.click(
    within(confirmation).getByRole('button', { name: 'Apply to development' }),
  );
  await screen.findByText('Merged; development app update pending');
  expect(
    screen.queryByText('Development applied and environment cleaned'),
  ).toBeNull();
  expect(
    screen
      .getByRole('link', { name: 'Review merge request' })
      .getAttribute('href'),
  ).toBe(merged.integration.mr_url);
  expect(api).toHaveBeenCalledWith(
    `/workbench/workspaces/${initial.id}/integrate`,
    { operation_id: expect.any(String), expected_version: 3 },
    'POST',
    expect.any(AbortSignal),
  );
});

it('keeps recorded environments accessible while an unavailable profile prevents new preparation', async () => {
  const current = environment({
    state: 'stopped',
    admission_open: false,
    preview: { ...environment().preview, state: 'stopped' },
  });
  vi.mocked(api).mockImplementation(async (path) =>
    path.endsWith('/workspaces')
      ? ({ available: false, items: [current] } as never)
      : (current as never),
  );
  render(<ProjectWorkspaces project={project} {...props()} />);
  await screen.findByText(
    'An administrator must connect the MIY development environment before starting this work.',
  );
  expect(
    screen
      .getByRole('button', { name: 'New development environment' })
      .hasAttribute('disabled'),
  ).toBe(true);
  await screen.findAllByText(current.branch);
  expect(
    screen.queryByRole('link', { name: 'Open app in new tab' }),
  ).toBeNull();
});

it('shows a reconnecting session the same server environment and hides unsupported or unverified app links', async () => {
  const current = environment({
    preview: { ...environment().preview, portal_url: 'javascript:alert(1)' },
  });
  vi.mocked(api).mockResolvedValue(current as never);
  const handlers = props();
  const { rerender, container } = render(
    <WorkspacePanel id={current.id} compact {...handlers} />,
  );
  await screen.findAllByText(current.branch);
  rerender(
    <WorkspacePanel
      id={current.id}
      compact
      {...handlers}
      tasks={[
        {
          id: 'existing-task',
          title: 'Existing environment session',
          stage: 'plan',
          status: 'idle',
          context: { workspace_id: current.id },
        } as unknown as Task,
      ]}
    />,
  );
  expect(
    screen.queryByRole('link', { name: 'Open app in new tab' }),
  ).toBeNull();
  expect(container.querySelector('iframe')).toBeNull();
  expect(vi.mocked(api).mock.calls.filter(([, body]) => !!body)).toHaveLength(
    0,
  );
});
