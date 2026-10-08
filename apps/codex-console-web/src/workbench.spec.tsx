import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api } from './api';
import { translate } from './i18n';
import {
  AppInstallations,
  WorkbenchApps,
  type StartWorkbenchTask,
} from './workbench';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));

const apps = [
  {
    app_id: 'candidate-review',
    title: 'Candidate review',
    title_translations: { 'ko-KR': '지원서 검토', 'en-US': 'Candidate review' },
    icon_key: 'clipboard-check',
    summary: '',
    capabilities: [],
    source_paths: [],
    release_unit: null,
    route_base: '/apps/candidate-review',
    preview_url: null,
    source_status: 'unconfigured',
    preview_status: 'unconfigured',
    deployment_status: 'unconfigured',
    limitations: [
      'source_not_configured',
      'release_not_configured',
      'preview_not_configured',
    ],
  },
  {
    app_id: 'calendar-helper',
    title: 'Calendar helper',
    title_translations: { 'ko-KR': '일정 도우미', 'en-US': 'Calendar helper' },
    icon_key: 'calendar',
    summary: '',
    capabilities: [],
    source_paths: ['app/calendar'],
    release_unit: 'miy-app',
    route_base: '/apps/calendar-helper',
    preview_url: 'https://preview.example.test/apps/calendar-helper',
    source_status: 'ready',
    preview_status: 'configured',
    deployment_status: 'configured',
    limitations: [],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, '', '/');
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/workbench/catalog')
      return {
        items: apps,
        projects: [],
        source_revision: null,
        source_dirty: false,
        checked_at: '2026-10-06T00:00:00Z',
      } as never;
    if (path === '/workbench/runtime')
      return { state: 'unconfigured', items: [], stale: true } as never;
    throw new Error('Unexpected API request');
  });
});

it('checks the selected independent project connection before creating its development task', async () => {
  let resolve!: (value: unknown) => void;
  const checked = new Promise((done) => {
    resolve = done;
  });
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/workbench/catalog')
      return {
        items: [
          {
            ...apps[0],
            discovery: 'source',
            source_status: 'ready',
            execution_status: 'configured',
            source_version: 1,
          },
        ],
        projects: [
          {
            id: 'project-check',
            app_id: apps[0].app_id,
            title: 'Independent project',
            summary: 'Develop this app',
            reuse_decision: 'new',
            reuse_notes: 'Need this app',
            created_at: '2026-10-08T00:00:00Z',
          },
        ],
        source_revision: null,
        source_dirty: false,
        checked_at: '2026-10-08T00:00:00Z',
      } as never;
    if (path === '/workbench/runtime')
      return { state: 'unconfigured', items: [], stale: true } as never;
    if (path === '/workbench/projects/project-check/execution-readiness')
      return checked as never;
    throw new Error('Unexpected API request');
  });
  const startTask = vi.fn<StartWorkbenchTask>().mockResolvedValue(undefined);
  render(
    <WorkbenchApps
      area="studio"
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      newTask={vi.fn()}
      startTask={startTask}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'Continue development' }),
  );
  expect(startTask).not.toHaveBeenCalled();
  resolve({
    project_id: 'project-check',
    app_id: apps[0].app_id,
    source_version: 1,
    state: 'reachable',
    failure_code: null,
    checked_at: '2026-10-08T00:00:00Z',
  });
  await waitFor(() => expect(startTask).toHaveBeenCalledTimes(1));
  expect(startTask.mock.calls[0][0]).toMatchObject({
    purpose: 'development',
    project_id: 'project-check',
    app_id: apps[0].app_id,
  });
});

const installation = {
  id: '9a28df58-bc6f-494b-9b8e-292ef5cc3b48',
  environment: 'development',
  origin: 'https://preview.example.test',
  enabled: true,
  state: 'configured',
  generation: 1,
  release_id: null,
  source_revision: null,
  artifact_digest: null,
  deployment: {
    request_id: 'a50b4fe2-bdb8-4a32-bf25-2d7e973898dc',
    action: 'deploy',
    state: 'unknown',
    failure_code: 'executor_unavailable',
    updated_at: '2026-10-06T01:00:00Z',
  },
};

it('offers source preparation for new projects and keeps development disabled until execution is configured', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/workbench/catalog')
      return {
        items: [
          {
            ...apps[0],
            discovery: 'source',
            source_status: 'ready',
            execution_status: 'unconfigured',
          },
        ],
        projects: [
          {
            id: 'new-project',
            app_id: apps[0].app_id,
            title: 'New project',
            summary: 'Build a review app',
            reuse_decision: 'new',
            reuse_notes: '',
            created_at: '2026-10-06T00:00:00Z',
          },
          {
            id: 'extended-project',
            app_id: 'calendar-helper',
            title: 'Existing project',
            summary: 'Extend calendar',
            reuse_decision: 'extend',
            reuse_notes: '',
            created_at: '2026-10-06T00:00:00Z',
          },
        ],
        source_revision: null,
        source_dirty: false,
        checked_at: '2026-10-06T00:00:00Z',
      } as never;
    if (path === '/workbench/runtime')
      return { state: 'unconfigured', items: [], stale: true } as never;
    if (path === '/workbench/source-setup/options')
      return { roots: [], templates: [] } as never;
    if (path === '/workbench/projects/new-project/source-setup')
      return { setup: null } as never;
    throw new Error('Unexpected request');
  });
  const startTask = vi.fn();
  render(
    <WorkbenchApps
      area="studio"
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={startTask}
      newTask={vi.fn()}
    />,
  );
  const project = (await screen.findByText('New project')).closest(
    '.stack',
  ) as HTMLElement;
  expect(
    (
      within(project).getByRole('button', {
        name: 'Continue development',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    screen.getAllByRole('button', { name: 'Prepare app source' }),
  ).toHaveLength(1);
  fireEvent.click(
    within(project).getByRole('button', { name: 'Prepare app source' }),
  );
  await within(project).findByText(
    'An administrator must configure a folder for creating apps before source preparation is available.',
  );
  expect(startTask).not.toHaveBeenCalled();
});

it('allows a bound project to recheck a source collision without exposing export or mutation', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/workbench/catalog')
      return {
        items: [
          {
            ...apps[0],
            discovery: 'source',
            source_status: 'invalid',
            source_version: 1,
            execution_status: 'unconfigured',
          },
        ],
        projects: [
          {
            id: 'collision-project',
            app_id: apps[0].app_id,
            title: 'Conflicting app',
            summary: 'Review connected source',
            reuse_decision: 'extend',
            reuse_notes: '',
            created_at: '2026-10-06T00:00:00Z',
          },
        ],
        checked_at: '2026-10-06T00:00:00Z',
      } as never;
    if (path === '/workbench/runtime')
      return { state: 'unconfigured', items: [], stale: true } as never;
    if (path.endsWith('/registration-status'))
      return {
        project_id: 'collision-project',
        app_id: apps[0].app_id,
        binding_version: 1,
        state: 'collision',
        source_revision: 'a'.repeat(40),
        definition_digest: `sha256:${'b'.repeat(64)}`,
        platform_state: 'ready',
        platform_checked_at: '2026-10-06T00:00:00Z',
        registered_source_revision: null,
        registered_definition_digest: null,
        definition_matches: null,
        revision_matches: null,
      } as never;
    throw new Error('Unexpected request');
  });
  const startTask = vi.fn();
  render(
    <WorkbenchApps
      area="studio"
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={startTask}
      newTask={vi.fn()}
    />,
  );
  const button = await screen.findByRole('button', {
    name: 'Check registration status',
  });
  expect(
    screen.queryByRole('button', { name: 'Download registration draft' }),
  ).toBeNull();
  expect(
    vi
      .mocked(api)
      .mock.calls.some(([path]) => path.endsWith('/registration-status')),
  ).toBe(false);
  fireEvent.click(button);
  await screen.findByText('This app ID is registered to a different source.');
  const region = screen.getByRole('region', { name: 'Platform registration' });
  expect(within(region).queryByRole('link')).toBeNull();
  expect(startTask).not.toHaveBeenCalled();
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
});

it('keeps unknown delivery separate from installed evidence and exposes no mutations', async () => {
  vi.mocked(api).mockResolvedValue({
    state: 'ready',
    stale: false,
    checked_at: '2026-10-06T01:01:00Z',
    items: [installation],
  });
  render(
    <AppInstallations
      appId="candidate-review"
      refresh={0}
      t={translate('en-US')}
    />,
  );
  const section = screen.getByRole('region', { name: 'App installations' });
  await within(section).findByText('Deployment: Unknown');
  expect(within(section).getByText('Not verified')).toBeTruthy();
  expect(
    within(section).getByText('Check the existing request before retrying.'),
  ).toBeTruthy();
  expect(
    within(section).getByText('Deployment records are not live health checks.'),
  ).toBeTruthy();
  expect(
    within(section)
      .getByRole('link', { name: installation.origin })
      .getAttribute('href'),
  ).toBe(installation.origin);
  expect(within(section).queryAllByRole('button')).toHaveLength(0);
  expect(api).toHaveBeenCalledWith(
    '/workbench/apps/candidate-review/installations',
    undefined,
    'GET',
    expect.any(AbortSignal),
  );
});

it('retains installation evidence on refresh failure and discards it when changing app', async () => {
  vi.mocked(api).mockResolvedValueOnce({
    state: 'ready',
    stale: false,
    checked_at: '2026-10-06T01:01:00Z',
    items: [{ ...installation, source_revision: 'a'.repeat(40) }],
  });
  const props = {
    appId: 'candidate-review',
    refresh: 0,
    t: translate('en-US'),
  };
  const view = render(<AppInstallations {...props} />);
  await screen.findByText('aaaaaaaaaaaa');
  vi.mocked(api).mockRejectedValue(new Error('offline'));
  view.rerender(<AppInstallations {...props} refresh={1} />);
  await screen.findByRole('alert');
  expect(screen.getByText(/Connection unavailable/).textContent).toContain(
    'Current state not verified',
  );
  expect(screen.getByText('aaaaaaaaaaaa')).toBeTruthy();
  view.rerender(<AppInstallations {...props} appId="another-app" />);
  expect(screen.queryByText('aaaaaaaaaaaa')).toBeNull();
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/workbench/apps/another-app/installations',
      undefined,
      'GET',
      expect.any(AbortSignal),
    ),
  );
});

it('starts a planning task bound to the exact configured development installation', async () => {
  vi.mocked(api).mockResolvedValue({
    state: 'ready',
    stale: false,
    checked_at: '2026-10-06T01:01:00Z',
    items: [{ ...installation, delivery_configured: true }],
  });
  const startTask = vi.fn().mockResolvedValue(undefined);
  render(
    <AppInstallations
      appId="candidate-review"
      refresh={0}
      t={translate('en-US')}
      startTask={startTask}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'Plan preview deployment' }),
  );
  await waitFor(() =>
    expect(startTask).toHaveBeenCalledWith(
      {
        app_id: 'candidate-review',
        installation_id: installation.id,
        purpose: 'deployment',
        area: 'apps',
      },
      'candidate-review · Plan preview deployment',
      expect.stringContaining('Plan a development preview deployment'),
    ),
  );
  expect(api).toHaveBeenCalledTimes(1);
});

it('discovers an unconfigured app with the manifest label and icon and explains restrictions', async () => {
  const startTask = vi.fn().mockResolvedValue(undefined);
  render(
    <WorkbenchApps
      area="studio"
      t={translate('ko-KR')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={startTask}
      newTask={vi.fn()}
    />,
  );
  const picker = await screen.findByRole('button', {
    name: '지원서 검토 등록된 앱',
  });
  expect(
    picker.querySelector('svg')?.classList.contains('lucide-clipboard-check'),
  ).toBe(true);
  fireEvent.change(screen.getByLabelText('앱 찾기'), {
    target: { value: '지원서' },
  });
  expect(screen.queryByRole('button', { name: /일정 도우미/ })).toBeNull();
  fireEvent.click(picker);
  const detail = screen.getByRole('region', { name: '선택한 앱' });
  expect(
    within(detail).getByRole('heading', { name: '지원서 검토' }),
  ).toBeTruthy();
  expect(
    within(detail).getByText('개발 소스가 연결되지 않았습니다.'),
  ).toBeTruthy();
  expect(
    within(detail).getByText('배포 단위가 설정되지 않았습니다.'),
  ).toBeTruthy();
  expect(
    within(detail).queryByRole('button', { name: '수정 개발' }),
  ).toBeNull();
  fireEvent.click(
    within(detail).getByRole('button', { name: '앱 연결 설정 검토' }),
  );
  await waitFor(() =>
    expect(startTask).toHaveBeenCalledWith(
      { area: 'studio', purpose: 'inspection', app_id: 'candidate-review' },
      '지원서 검토: 앱 연결 설정 검토',
      expect.stringContaining('do not guess'),
    ),
  );
});

it('uses configured source for development without claiming preview or deployment verification', async () => {
  const startTask = vi.fn().mockResolvedValue(undefined);
  render(
    <WorkbenchApps
      area="studio"
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={startTask}
      newTask={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Calendar helper Source available',
    }),
  );
  expect(
    screen.getByText('Preview configured; availability not verified'),
  ).toBeTruthy();
  expect(
    screen.getByText('Release configured; deployment not verified'),
  ).toBeTruthy();
  expect(
    screen
      .getByRole('link', { name: 'Open development app' })
      .getAttribute('href'),
  ).toBe(apps[1].preview_url);
  fireEvent.click(screen.getByRole('button', { name: 'Develop app' }));
  await waitFor(() =>
    expect(startTask).toHaveBeenCalledWith(
      { area: 'studio', purpose: 'development', app_id: 'calendar-helper' },
      'Calendar helper: Develop app',
      expect.any(String),
    ),
  );
});

it('connects an explicit owner-selected source without inferring a path', async () => {
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) => {
    if (args[0] === '/workbench/apps/new-independent-app/source') {
      return { app_id: 'new-independent-app' } as never;
    }
    return original(...args);
  });
  render(
    <WorkbenchApps
      area="studio"
      t={translate('ko-KR')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={vi.fn()}
      newTask={vi.fn()}
    />,
  );
  await screen.findByText('지원서 검토');
  fireEvent.click(screen.getByRole('button', { name: '앱 소스 연결' }));
  fireEvent.change(screen.getByLabelText('앱 식별자'), {
    target: { value: 'new-independent-app' },
  });
  fireEvent.change(screen.getByLabelText('저장소 작업 경로'), {
    target: { value: '/owner/apps/new-app' },
  });
  fireEvent.click(screen.getAllByRole('button', { name: '앱 소스 연결' })[1]);
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/workbench/apps/new-independent-app/source',
      { repository_root: '/owner/apps/new-app', version: 0 },
      'PUT',
    ),
  );
  await waitFor(() =>
    expect(screen.queryByLabelText('저장소 작업 경로')).toBeNull(),
  );
});

it('keeps a connected source visible while preventing work without an executor', async () => {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === '/workbench/catalog')
      return {
        items: [
          {
            ...apps[1],
            discovery: 'source',
            source_root: '/owner/apps/calendar',
            execution_status: 'unconfigured',
            limitations: ['executor_not_configured'],
          },
        ],
        projects: [],
        source_revision: null,
        source_dirty: false,
        checked_at: '2026-10-06T00:00:00Z',
      } as never;
    if (path === '/workbench/runtime')
      return { state: 'unconfigured', items: [], stale: true } as never;
    if (path === '/workbench/apps/calendar-helper/installations')
      return {
        state: 'ready',
        stale: false,
        items: [
          {
            ...installation,
            delivery_configured: true,
          },
        ],
      } as never;
    throw new Error('Unexpected API request');
  });
  const startTask = vi.fn();
  render(
    <WorkbenchApps
      area="studio"
      t={translate('en-US')}
      tasks={[]}
      openTask={vi.fn()}
      startTask={startTask}
      newTask={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Calendar helper Source available',
    }),
  );
  expect(
    screen.getByText(
      'Configure an isolated execution environment for this app.',
    ),
  ).toBeTruthy();
  const develop = screen.getByRole('button', {
    name: 'Develop app',
  }) as HTMLButtonElement;
  expect(develop.disabled).toBe(true);
  fireEvent.click(develop);
  await screen.findByText('Deployment: Unknown');
  expect(
    screen.queryByRole('button', { name: 'Plan preview deployment' }),
  ).toBeNull();
  expect(startTask).not.toHaveBeenCalled();
});
