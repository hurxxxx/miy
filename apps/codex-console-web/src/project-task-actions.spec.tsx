import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { ProjectTaskActions } from './project-task-actions';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
type S = components['schemas'];
const project: S['ProjectOut'] = {
  id: 'project-1',
  app_id: 'sample-app',
  title: 'App project',
  summary: 'Build an app',
  reuse_decision: 'new',
  reuse_notes: 'Need a new app',
  created_at: '2026-10-08T00:00:00Z',
};
const source: S['AppDescriptor'] = {
  app_id: 'sample-app',
  title: 'Sample app',
  title_translations: {},
  icon_key: 'app-window',
  summary: '',
  capabilities: [],
  source_paths: ['.'],
  release_unit: null,
  route_base: '/apps/sample-app',
  preview_url: null,
  discovery: 'source',
  source_root: '/synthetic/app',
  source_version: 1,
  source_status: 'ready',
  execution_status: 'configured',
  preview_status: 'unconfigured',
  deployment_status: 'unconfigured',
  limitations: [],
};
const observation: S['ProjectExecutionReadinessOut'] = {
  project_id: project.id,
  app_id: project.app_id,
  source_version: 1,
  state: 'reachable',
  failure_code: null,
  checked_at: '2026-10-08T00:00:00Z',
};
const defaults = {
  project,
  source,
  busy: false,
  registrationAvailable: true,
  scope: '',
  t: translate('en-US'),
  onStart: vi.fn(async () => {}),
};
const deferred = () => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockResolvedValue(observation as never);
});

it('checks fresh metadata before development and does not cache an execution permit', async () => {
  render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Check execution environment connection',
    }),
  );
  await screen.findByText('Execution environment connection confirmed.');
  expect(defaults.onStart).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Continue development' }));
  await waitFor(() =>
    expect(defaults.onStart).toHaveBeenCalledExactlyOnceWith('development'),
  );
  expect(api).toHaveBeenCalledTimes(2);
  expect(screen.getByText(/Permissions and sandbox policies/)).not.toBeNull();
});

it('checks metadata before a new registration task as well', async () => {
  render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(
    screen.getByRole('button', { name: 'New registration task' }),
  );
  await waitFor(() =>
    expect(defaults.onStart).toHaveBeenCalledExactlyOnceWith('registration'),
  );
  expect(api).toHaveBeenCalledTimes(1);
});

it('keeps a configured but unreachable executor from starting a task', async () => {
  vi.mocked(api).mockResolvedValue({
    ...observation,
    state: 'unavailable',
    failure_code: 'app_executor_unavailable',
  } as never);
  render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue development' }));
  await screen.findByText(
    'Execution environment connection could not be confirmed.',
  );
  expect(defaults.onStart).not.toHaveBeenCalled();
});

it.each([
  { source_version: 2 },
  { project_id: 'other-project' },
  { app_id: 'other-app' },
  { failure_code: 'not-a-valid-success' },
  { state: 'unknown-state' },
  { checked_at: 'invalid-time' },
])('rejects mismatched or malformed success metadata %j', async (change) => {
  vi.mocked(api).mockResolvedValue({ ...observation, ...change } as never);
  render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue development' }));
  await screen.findByRole('alert');
  expect(defaults.onStart).not.toHaveBeenCalled();
});

it.each(['version', 'project', 'selection', 'configuration'])(
  'discards a late connection response after %s changes',
  async (change) => {
    const request = deferred();
    vi.mocked(api).mockReturnValue(request.promise as never);
    const view = render(<ProjectTaskActions {...defaults} />);
    fireEvent.click(
      screen.getByRole('button', { name: 'Continue development' }),
    );
    const signal = vi.mocked(api).mock.calls[0][3] as AbortSignal;
    view.rerender(
      <ProjectTaskActions
        {...defaults}
        source={
          change === 'version'
            ? { ...source, source_version: 2 }
            : change === 'configuration'
              ? { ...source, execution_status: 'unconfigured' }
              : source
        }
        project={
          change === 'project' ? { ...project, id: 'project-2' } : project
        }
        scope={change === 'selection' ? 'another-app' : ''}
      />,
    );
    expect(signal.aborted).toBe(true);
    request.resolve(observation);
    await waitFor(() =>
      expect(
        screen.queryByText('Execution environment connection confirmed.'),
      ).toBeNull(),
    );
    expect(defaults.onStart).not.toHaveBeenCalled();
  },
);

it('discards a response when logout removes the authenticated project lifetime', async () => {
  const request = deferred();
  vi.mocked(api).mockReturnValue(request.promise as never);
  const view = render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue development' }));
  const signal = vi.mocked(api).mock.calls[0][3] as AbortSignal;
  view.unmount();
  expect(signal.aborted).toBe(true);
  request.resolve(observation);
  await request.promise;
  expect(defaults.onStart).not.toHaveBeenCalled();
});

it('ignores immediate duplicate clicks while one check is in flight', async () => {
  const request = deferred();
  vi.mocked(api).mockReturnValue(request.promise as never);
  render(<ProjectTaskActions {...defaults} />);
  const button = screen.getByRole('button', { name: 'Continue development' });
  fireEvent.click(button);
  fireEvent.click(button);
  fireEvent.click(
    screen.getByRole('button', { name: 'New registration task' }),
  );
  expect(api).toHaveBeenCalledTimes(1);
  request.resolve(observation);
  await waitFor(() => expect(defaults.onStart).toHaveBeenCalledTimes(1));
});

it('requires an authenticated status response instead of starting on an API error', async () => {
  vi.mocked(api).mockRejectedValue(new ApiError('unauthenticated'));
  render(<ProjectTaskActions {...defaults} />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue development' }));
  await screen.findByRole('alert');
  expect(defaults.onStart).not.toHaveBeenCalled();
});

it.each([
  undefined,
  {
    ...source,
    discovery: 'checkout' as const,
    execution_status: 'platform' as const,
  },
])(
  'retains unconnected planning and official checkout tasks without a remote check',
  async (source) => {
    render(<ProjectTaskActions {...defaults} source={source} />);
    fireEvent.click(
      screen.getByRole('button', { name: 'Continue development' }),
    );
    await waitFor(() =>
      expect(defaults.onStart).toHaveBeenCalledExactlyOnceWith('development'),
    );
    expect(api).not.toHaveBeenCalled();
  },
);

it('keeps development disabled for missing executor settings but lets the owner inspect connection status', () => {
  render(
    <ProjectTaskActions
      {...defaults}
      source={{ ...source, execution_status: 'unconfigured' }}
    />,
  );
  expect(
    screen.getByRole('button', { name: 'Continue development' }),
  ).toHaveProperty('disabled', true);
  expect(
    screen.getByRole('button', {
      name: 'Check execution environment connection',
    }),
  ).toHaveProperty('disabled', false);
  expect(
    screen.queryByRole('button', { name: 'New registration task' }),
  ).toBeNull();
});
