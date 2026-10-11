import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

import { IndependentAppHost } from './IndependentAppHost';
import { INDEPENDENT_APP_ROUTE } from './independent-app-host';
import {
  issueIndependentLaunch,
  useIndependentApps,
  type IndependentApp,
} from './independent-apps-api';
import { resolveIndependentNavigation } from './independent-app-navigation';

vi.mock('./independent-app-navigation', () => ({
  resolveIndependentNavigation: vi.fn(),
}));
const auth = vi.hoisted(() => ({
  token: 'platform-login-token',
  user: { id: 'actor-1' },
}));

vi.mock('@/src/platform/auth/auth-context', () => ({
  useAuth: () => auth,
}));
const language = vi.hoisted(() => ({ value: 'ko-KR' }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: language.value },
  }),
}));
vi.mock('./independent-apps-api', async (original) => ({
  ...(await original<typeof import('./independent-apps-api')>()),
  useIndependentApps: vi.fn(),
  issueIndependentLaunch: vi.fn(),
}));

const item = {
  definition: {
    definition: {
      app_id: 'candidate-review',
      display: {
        name: 'Candidate review',
        translations: { 'ko-KR': '지원서 검토' },
      },
      entrypoints: { ui: '/' },
    },
  },
  installations: [
    {
      id: 'install-1',
      origin: 'https://app.example.test',
      generation: 1,
      launchable: true,
      ui_entrypoint: '/',
    },
  ],
} as unknown as IndependentApp;

beforeEach(() => {
  vi.clearAllMocks();
  document.documentElement.classList.remove('dark');
  language.value = 'ko-KR';
  auth.token = 'platform-login-token';
  vi.mocked(resolveIndependentNavigation).mockResolvedValue({
    target: { app_id: 'planner' },
    path: '/apps/planner',
    identity: 'planner',
    label: 'Planner',
  });
  vi.mocked(useIndependentApps).mockReturnValue({
    items: [item],
    loading: false,
    failed: false,
  });
});

it('updates effective theme and locale in place without restarting authentication or iframe', async () => {
  vi.mocked(issueIndependentLaunch).mockResolvedValue({
    code: 'c'.repeat(43),
    app_origin: 'https://app.example.test',
    expires_at: new Date(Date.now() + 60000).toISOString(),
  });
  const rendered = render(view());
  const frame = screen.getByTitle('지원서 검토') as HTMLIFrameElement;
  const target = frame.contentWindow;
  if (!target) throw new Error('Expected an iframe window');
  const send = vi.spyOn(target, 'postMessage');
  fireEvent.load(frame);
  fireEvent(
    window,
    new MessageEvent('message', {
      source: frame.contentWindow,
      origin: 'https://app.example.test',
      data: {
        type: 'miy.app.ready',
        version: 1,
        installation_id: 'install-1',
        request_id: '12345678-1234-4321-8765-123456789abc',
        code_challenge: 'a'.repeat(43),
        ui_context_version: 1,
      },
    }),
  );
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  expect(send).toHaveBeenLastCalledWith(
    expect.objectContaining({
      ui_context: { version: 1, sequence: 0, theme: 'light', locale: 'ko-KR' },
    }),
    'https://app.example.test',
  );
  await act(async () => {
    document.documentElement.classList.add('dark');
  });
  await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
  language.value = 'en-US';
  rendered.rerender(view());
  await waitFor(() => expect(send).toHaveBeenCalledTimes(3));
  expect(send).toHaveBeenLastCalledWith(
    expect.objectContaining({
      type: 'miy.app.context',
      ui_context: { version: 1, sequence: 2, theme: 'dark', locale: 'en-US' },
    }),
    'https://app.example.test',
  );
  expect(issueIndependentLaunch).toHaveBeenCalledOnce();
  expect(screen.getByTitle('Candidate review')).toBe(frame);
  rendered.unmount();
  document.documentElement.classList.remove('dark');
  await Promise.resolve();
  expect(send).toHaveBeenCalledTimes(3);
});

it('launches the active release entrypoint while a newer source definition is pending', () => {
  vi.mocked(useIndependentApps).mockReturnValue({
    items: [
      {
        ...item,
        definition: {
          ...item.definition,
          definition: {
            ...item.definition.definition,
            entrypoints: { ui: '/pending', api: '/api', health: '/healthz' },
          },
        },
        installations: [
          { ...item.installations[0], ui_entrypoint: '/installed' },
        ],
      },
    ],
    loading: false,
    failed: false,
  });
  render(view());
  expect(screen.getByTitle('지원서 검토').getAttribute('src')).toBe(
    'https://app.example.test/installed',
  );
});

const view = () => (
  <MemoryRouter initialEntries={['/apps/candidate-review/installed/install-1']}>
    <Routes>
      <Route path={INDEPENDENT_APP_ROUTE} element={<IndependentAppHost />} />
    </Routes>
  </MemoryRouter>
);

it('uses a separate sandboxed origin and unmounts the app when admission is withdrawn', () => {
  const rendered = render(view());
  const frame = screen.getByTitle('지원서 검토');
  expect(frame.getAttribute('src')).toBe('https://app.example.test/');
  expect(frame.getAttribute('sandbox')).toBe(
    'allow-scripts allow-same-origin allow-forms allow-downloads',
  );
  expect(frame.getAttribute('referrerPolicy')).toBe('no-referrer');
  expect(
    screen
      .getByRole('link', { name: 'independentApps.openStandalone' })
      .getAttribute('rel'),
  ).toBe('noopener noreferrer');
  vi.mocked(useIndependentApps).mockReturnValue({
    items: [],
    loading: false,
    failed: false,
  });
  rendered.rerender(view());
  expect(screen.queryByTitle('지원서 검토')).toBeNull();
  expect(screen.getByRole('alert').textContent).toBe(
    'independentApps.unavailable',
  );
});

it('invalidates a pending launch if the selected installation is revoked', async () => {
  let complete!: (
    value: Awaited<ReturnType<typeof issueIndependentLaunch>>,
  ) => void;
  vi.mocked(issueIndependentLaunch).mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const rendered = render(view());
  const frame = screen.getByTitle('지원서 검토') as HTMLIFrameElement;
  const target = frame.contentWindow;
  if (!target) throw new Error('Expected an iframe window');
  const send = vi.spyOn(target, 'postMessage');
  fireEvent.load(frame);
  fireEvent(
    window,
    new MessageEvent('message', {
      source: frame.contentWindow,
      origin: 'https://app.example.test',
      data: {
        type: 'miy.app.ready',
        version: 1,
        installation_id: 'install-1',
        request_id: '12345678-1234-4321-8765-123456789abc',
        code_challenge: 'a'.repeat(43),
      },
    }),
  );
  await waitFor(() => expect(issueIndependentLaunch).toHaveBeenCalledOnce());
  const signal = vi.mocked(issueIndependentLaunch).mock.calls[0][3];
  vi.mocked(useIndependentApps).mockReturnValue({
    items: [],
    loading: false,
    failed: false,
  });
  rendered.rerender(view());
  expect(signal.aborted).toBe(true);
  complete({
    code: 'c'.repeat(43),
    app_origin: 'https://app.example.test',
    expires_at: new Date(Date.now() + 60000).toISOString(),
  });
  await Promise.resolve();
  expect(send).not.toHaveBeenCalled();
});

async function navigationHost() {
  vi.mocked(issueIndependentLaunch).mockResolvedValue({
    code: 'c'.repeat(43),
    app_origin: 'https://app.example.test',
    expires_at: new Date(Date.now() + 60000).toISOString(),
  });
  const root = () => (
    <MemoryRouter
      initialEntries={['/apps/candidate-review/installed/install-1']}
    >
      <Routes>
        <Route path={INDEPENDENT_APP_ROUTE} element={<IndependentAppHost />} />
        <Route path="/apps/planner" element={<h1>Planner destination</h1>} />
      </Routes>
    </MemoryRouter>
  );
  const rendered = render(root());
  const frame = screen.getByTitle('지원서 검토') as HTMLIFrameElement;
  fireEvent.load(frame);
  const target = frame.contentWindow;
  if (!target) throw new Error('Expected an iframe window');
  const sent = vi.spyOn(target, 'postMessage');
  const nonce = '12345678-1234-4321-8765-123456789abc';
  const send = (data: object) =>
    fireEvent(
      window,
      new MessageEvent('message', {
        source: target,
        origin: 'https://app.example.test',
        data: {
          version: 1,
          installation_id: 'install-1',
          request_id: nonce,
          ...data,
        },
      }),
    );
  send({
    type: 'miy.app.ready',
    code_challenge: 'a'.repeat(43),
    navigation_version: 1,
  });
  await waitFor(() => expect(sent).toHaveBeenCalledOnce());
  send({
    type: 'miy.app.navigation.request',
    navigation_version: 1,
    navigation_id: '22222222-2222-4222-8222-222222222222',
    target: { app_id: 'planner' },
  });
  await screen.findByRole('button', {
    name: 'independentApps.navigation.open',
  });
  return { rendered, root, sent, send };
}

it('presents a bounded offer and navigates only after a host button click and fresh recheck', async () => {
  await navigationHost();
  expect(
    screen.queryByRole('heading', { name: 'Planner destination' }),
  ).toBeNull();
  expect(resolveIndependentNavigation).toHaveBeenCalledOnce();
  fireEvent.click(
    screen.getByRole('button', { name: 'independentApps.navigation.open' }),
  );
  await screen.findByRole('heading', { name: 'Planner destination' });
  expect(resolveIndependentNavigation).toHaveBeenCalledTimes(2);
});

it('removes a visible offer immediately when login changes and rejects a revoked target on click', async () => {
  const run = await navigationHost();
  auth.token = 'second-login';
  run.rendered.rerender(run.root());
  expect(
    screen.queryByRole('button', { name: 'independentApps.navigation.open' }),
  ).toBeNull();
  run.rendered.unmount();
  await navigationHost();
  vi.mocked(resolveIndependentNavigation).mockResolvedValueOnce(null);
  fireEvent.click(
    screen.getByRole('button', { name: 'independentApps.navigation.open' }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'independentApps.navigation.open' }),
    ).toBeNull(),
  );
  expect(
    screen.queryByRole('heading', { name: 'Planner destination' }),
  ).toBeNull();
});
