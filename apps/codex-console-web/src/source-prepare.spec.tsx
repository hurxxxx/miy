import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';
import { translate } from './i18n';
import { SourcePrepare } from './source-prepare';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));

const path = '/workbench/projects/project-one/source-setup';
const bundle = 'sha256:' + 'a'.repeat(64);
const options = {
  roots: [{ id: 'approved-root', label: 'My apps' }],
  templates: [
    {
      id: 'basic',
      name: 'Basic',
      runtime_profile: 'web-api-v1',
      bundle_digest: bundle,
      sdk_version: '0.1.0',
    },
    {
      id: 'private-notes',
      name: 'Private notes',
      runtime_profile: 'web-api-postgres-v1',
      bundle_digest: bundle,
      sdk_version: '0.1.0',
    },
  ],
};
const saved = {
  operation_id: 'bc58aef7-8d6e-4e7c-9599-5a55c094fb80',
  project_id: 'project-one',
  app_id: 'new-app',
  root_id: 'approved-root',
  template_id: 'basic',
  repository: 'https://git.example/team/new-app.git',
  bundle_digest: bundle,
  state: 'preparing',
  source_root: null,
  source_revision: null,
  source_version: null,
  failure_code: null,
  created_at: '2026-10-06T00:00:00Z',
  updated_at: '2026-10-06T00:00:00Z',
};
const completed = {
  ...saved,
  state: 'ready',
  source_root: '/approved/new-app',
  source_revision: 'b'.repeat(40),
  source_version: 1,
};
const t = translate('en-US');

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api).mockImplementation(async (url) => {
    if (url.endsWith('/options')) return options as never;
    return { setup: null } as never;
  });
});
afterEach(() => vi.useRealTimers());

it('requires explicit creation roots and does not create source while loading or displaying options', async () => {
  vi.mocked(api).mockImplementation(
    async (url) =>
      (url.endsWith('/options')
        ? { ...options, roots: [] }
        : { setup: null }) as never,
  );
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />);
  await screen.findByText(
    'An administrator must configure a folder for creating apps before source preparation is available.',
  );
  expect(
    screen.queryByRole('button', { name: 'Prepare app source' }),
  ).toBeNull();
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
});

it('prepares the chosen fixed template once and reports source readiness without starting execution', async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (url, _body, method) => {
    if (method === 'POST')
      return (await new Promise<unknown>((resolve) => {
        finish = resolve;
      })) as never;
    return (url.endsWith('/options') ? options : { setup: null }) as never;
  });
  const ready = vi.fn();
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={ready} />);
  fireEvent.change(await screen.findByLabelText('App repository URL'), {
    target: { value: saved.repository },
  });
  fireEvent.change(screen.getByLabelText('Starter template'), {
    target: { value: 'private-notes' },
  });
  const submit = screen.getByRole('button', {
    name: 'Prepare app source',
  });
  fireEvent.click(submit);
  fireEvent.click(submit);
  const requests = vi
    .mocked(api)
    .mock.calls.filter((call) => call[2] === 'POST');
  expect(requests).toHaveLength(1);
  expect(requests[0]).toEqual([
    path,
    {
      operation_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
      root_id: 'approved-root',
      template_id: 'private-notes',
      repository: saved.repository,
      expected_bundle_digest: bundle,
    },
    'POST',
    expect.any(AbortSignal),
  ]);
  await act(async () =>
    finish({
      ...completed,
      operation_id: (requests[0][1] as typeof saved).operation_id,
    }),
  );
  await screen.findByText('App source prepared');
  expect(ready).toHaveBeenCalledTimes(1);
  expect(
    screen.getByText(
      'Source is connected. Check the app execution environment before starting development.',
    ),
  ).toBeTruthy();
});

it('reads the saved request after a lost response and resumes the same immutable operation', async () => {
  let postBody: Record<string, unknown> | undefined;
  let reads = 0;
  let posts = 0;
  vi.mocked(api).mockImplementation(async (url, body, method) => {
    if (url.endsWith('/options')) return options as never;
    if (method === 'POST') {
      posts++;
      if (posts === 1) {
        postBody = body as Record<string, unknown>;
        throw new Error('response lost');
      }
      expect(body).toEqual(postBody);
      return completed as never;
    }
    reads++;
    return {
      setup:
        reads === 1
          ? null
          : { ...saved, operation_id: postBody?.operation_id, state: 'failed' },
    } as never;
  });
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText('App repository URL'), {
    target: { value: saved.repository },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Prepare app source' }));
  await screen.findByText(
    'The preparation result is unknown. Check the saved request before continuing.',
  );
  expect(
    (
      screen.getByRole('button', {
        name: 'Continue source preparation',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByLabelText('App repository URL') as HTMLInputElement).disabled,
  ).toBe(true);
  fireEvent.click(
    screen.getByRole('button', { name: 'Check preparation status' }),
  );
  await screen.findByText(
    'Source preparation stopped. Continue the same request to resume.',
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Continue source preparation' }),
  );
  await screen.findByText('App source prepared');
  expect(posts).toBe(2);
});

it('reloads an existing conflict as read-only and never overwrites the source', async () => {
  vi.mocked(api).mockImplementation(
    async (url) =>
      (url.endsWith('/options')
        ? options
        : { setup: { ...saved, state: 'conflict' } }) as never,
  );
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />);
  await screen.findByText(
    'The source folder needs review. Existing files have been preserved.',
  );
  expect(
    (
      screen.getByRole('button', {
        name: 'Continue source preparation',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByLabelText('App repository URL') as HTMLInputElement).value,
  ).toBe(saved.repository);
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
});

it('cancels a departed project request and ignores its late completion', async () => {
  let finish!: (value: unknown) => void;
  let signal: AbortSignal | undefined;
  vi.mocked(api).mockImplementation(
    async (url, _body, method, requestSignal) => {
      if (method === 'POST') {
        signal = requestSignal;
        return (await new Promise<unknown>((resolve) => {
          finish = resolve;
        })) as never;
      }
      return (url.endsWith('/options') ? options : { setup: null }) as never;
    },
  );
  const ready = vi.fn();
  const view = render(
    <SourcePrepare projectId="project-one" t={t} onPrepared={ready} />,
  );
  fireEvent.change(await screen.findByLabelText('App repository URL'), {
    target: { value: saved.repository },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Prepare app source' }));
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(completed));
  expect(ready).not.toHaveBeenCalled();
});

it('bounds an unanswered preparation request and requires status lookup after the deadline', async () => {
  vi.mocked(api).mockImplementation(async (url, _body, method, signal) => {
    if (method === 'POST')
      return (await new Promise((_resolve, reject) => {
        signal?.addEventListener(
          'abort',
          () => reject(new DOMException('Aborted', 'AbortError')),
          { once: true },
        );
      })) as never;
    return (url.endsWith('/options') ? options : { setup: null }) as never;
  });
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText('App repository URL'), {
    target: { value: saved.repository },
  });
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole('button', { name: 'Prepare app source' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30000);
  });
  expect(
    screen.getByText(
      'The preparation result is unknown. Check the saved request before continuing.',
    ),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole('button', {
        name: 'Continue source preparation',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[2] === 'POST'),
  ).toHaveLength(1);
});

it('refreshes the app catalog when a lost successful response is recovered by reading status', async () => {
  let accepted = false;
  vi.mocked(api).mockImplementation(async (url, _body, method) => {
    if (url.endsWith('/options')) return options as never;
    if (method === 'POST') {
      accepted = true;
      throw new Error('lost response');
    }
    return { setup: accepted ? completed : null } as never;
  });
  const ready = vi.fn();
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={ready} />);
  fireEvent.change(await screen.findByLabelText('App repository URL'), {
    target: { value: saved.repository },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Prepare app source' }));
  await screen.findByText(
    'The preparation result is unknown. Check the saved request before continuing.',
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Check preparation status' }),
  );
  await screen.findByText('App source prepared');
  expect(ready).toHaveBeenCalledTimes(1);
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[2] === 'POST'),
  ).toHaveLength(1);
});

it.each([
  ['app_setup_invalid', true],
  ['app_setup_bundle_invalid', false],
])(
  'allows correcting a rejected input only after confirming no saved intent (%s)',
  async (code, editable) => {
    vi.mocked(api).mockImplementation(async (url, _body, method) => {
      if (url.endsWith('/options')) return options as never;
      if (method === 'POST') throw new ApiError(code);
      return { setup: null } as never;
    });
    render(
      <SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />,
    );
    fireEvent.change(await screen.findByLabelText('App repository URL'), {
      target: { value: 'http://git.example/app' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Prepare app source' }));
    await screen.findByRole('alert');
    expect(
      (screen.getByLabelText('App repository URL') as HTMLInputElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(
      screen.getByRole('button', { name: 'Check preparation status' }),
    );
    await waitFor(() =>
      expect(screen.queryByText('Loading source preparation')).toBeNull(),
    );
    expect(
      (screen.getByLabelText('App repository URL') as HTMLInputElement)
        .disabled,
    ).toBe(!editable);
    expect(
      (screen.getByLabelText('App repository URL') as HTMLInputElement).value,
    ).toBe('http://git.example/app');
  },
);

it('does not authorize preparation when current saved state cannot be read', async () => {
  vi.mocked(api).mockImplementation(async (url) => {
    if (url.endsWith('/options')) return options as never;
    throw new Error('offline');
  });
  render(<SourcePrepare projectId="project-one" t={t} onPrepared={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(
    screen.queryByRole('button', { name: 'Prepare app source' }),
  ).toBeNull();
  expect(vi.mocked(api).mock.calls.every((call) => call[2] === 'GET')).toBe(
    true,
  );
});
