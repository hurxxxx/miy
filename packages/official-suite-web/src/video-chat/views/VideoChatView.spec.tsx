import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  createVideoChatSession,
  listVideoChatSessions,
  type VideoChatSession,
} from '../api/video-chat-api';
import { VideoChatView } from './VideoChatView';

const translation = vi.hoisted(() => ({
  t: (key: string) => key,
  i18n: { language: 'en-US' },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => translation }));
vi.mock('../api/video-chat-api', async (original) => ({
  ...(await original<typeof import('../api/video-chat-api')>()),
  createVideoChatSession: vi.fn(),
  listVideoChatSessions: vi.fn(),
}));
const room: VideoChatSession = {
  id: 'room-one',
  meeting_id: null,
  room_name: 'synthetic-room',
  title: 'Current room',
  status: 'open',
  provider: 'livekit',
  started_by_id: 'owner',
  started_by_name: 'Owner',
  started_at: '2026-10-06T10:00:00Z',
  ended_at: null,
  recording_status: 'idle',
  recording_egress_id: null,
  recording_id: null,
  captions_status: 'off',
  captions_started_at: null,
  captions_ended_at: null,
  created_at: '2026-10-06T10:00:00Z',
  updated_at: '2026-10-06T10:00:00Z',
};
const response = (items = [room]) => ({ items, total: items.length });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function Location() {
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">{useLocation().pathname}</output>
      <button onClick={() => navigate('/elsewhere')}>Leave lobby</button>
    </>
  );
}
function view(token: string | null = 'current-session', strict = false) {
  const content = (
    <AuthContext.Provider
      value={{ token, user: { time_zone: 'UTC' } } as AuthContextValue}
    >
      <MemoryRouter initialEntries={['/apps/video-chat']}>
        <Location />
        <Routes>
          <Route path="/apps/video-chat" element={<VideoChatView />} />
          <Route path="*" element={<div>Other view</div>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  );
  return strict ? <StrictMode>{content}</StrictMode> : content;
}
const create = () =>
  fireEvent.click(
    screen.getByRole('button', { name: 'apps:videoChat.createRoom' }),
  );
const title = () =>
  screen.getByRole('textbox', { name: 'apps:videoChat.createTitleLabel' });
beforeEach(() => {
  vi.clearAllMocks();
  translation.t = (key: string) => key;
  vi.mocked(listVideoChatSessions).mockResolvedValue(response());
  vi.mocked(createVideoChatSession).mockResolvedValue(room);
  Object.defineProperty(window.navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it('lists active rooms and the six most recent ended rooms', async () => {
  vi.mocked(listVideoChatSessions).mockResolvedValue(
    response([
      room,
      ...Array.from({ length: 7 }, (_, n) => ({
        ...room,
        id: `ended-${n}`,
        title: `Ended ${n}`,
        status: 'ended' as const,
      })),
    ]),
  );
  render(view());
  await screen.findByText(room.title);
  expect(listVideoChatSessions).toHaveBeenCalledExactlyOnceWith(
    'current-session',
  );
  expect(screen.getByText('Ended 5')).toBeTruthy();
  expect(screen.queryByText('Ended 6')).toBeNull();
});
it('creates once with a trimmed title and the unchanged room route', async () => {
  const pending = deferred<VideoChatSession>();
  vi.mocked(createVideoChatSession).mockReturnValue(pending.promise);
  render(view());
  fireEvent.change(title(), { target: { value: '  Planning room  ' } });
  create();
  create();
  expect(createVideoChatSession).toHaveBeenCalledExactlyOnceWith(
    'current-session',
    { title: 'Planning room' },
  );
  await act(async () => pending.resolve(room));
  expect(screen.getByTestId('location').textContent).toBe(
    '/apps/video-chat/sessions/room-one',
  );
});
it('uses null for an empty title and retains a rejected draft for explicit retry', async () => {
  vi.mocked(createVideoChatSession).mockRejectedValueOnce(
    new Error('Create denied'),
  );
  render(view());
  await act(async () => create());
  expect(createVideoChatSession).toHaveBeenCalledWith('current-session', {
    title: null,
  });
  expect(screen.getByText('Create denied')).toBeTruthy();
  fireEvent.change(title(), { target: { value: 'Retry room' } });
  await act(async () => create());
  expect(createVideoChatSession).toHaveBeenCalledTimes(2);
});
it('shows load failure and refreshes only after the explicit request', async () => {
  vi.mocked(listVideoChatSessions).mockRejectedValueOnce(
    new Error('List denied'),
  );
  render(view());
  await screen.findByText('List denied');
  expect(listVideoChatSessions).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByTitle('apps:videoChat.refresh'));
  await screen.findByText(room.title);
  expect(screen.queryByText('List denied')).toBeNull();
});
it('does not show an old account list after the next account loads', async () => {
  const pending = deferred<ReturnType<typeof response>>();
  vi.mocked(listVideoChatSessions).mockReturnValueOnce(pending.promise);
  const mounted = render(view('old-session'));
  mounted.rerender(view('new-session'));
  await screen.findByText(room.title);
  await act(async () =>
    pending.resolve(response([{ ...room, title: 'Private old room' }])),
  );
  expect(screen.queryByText('Private old room')).toBeNull();
  expect(screen.getByText(room.title)).toBeTruthy();
});
it.each(['resolve', 'reject'] as const)(
  'ignores an old create %s after a login changes',
  async (finish) => {
    const pending = deferred<VideoChatSession>();
    vi.mocked(createVideoChatSession).mockReturnValueOnce(pending.promise);
    const mounted = render(view('old-session'));
    fireEvent.change(title(), { target: { value: 'Private draft' } });
    create();
    mounted.rerender(view('new-session'));
    await act(async () =>
      finish === 'resolve'
        ? pending.resolve(room)
        : pending.reject(new Error('Old create failed')),
    );
    expect(screen.getByTestId('location').textContent).toBe('/apps/video-chat');
    expect(screen.queryByDisplayValue('Private draft')).toBeNull();
    expect(screen.queryByText('Old create failed')).toBeNull();
  },
);
it('does not navigate back after a pending create outlives its lobby', async () => {
  const pending = deferred<VideoChatSession>();
  vi.mocked(createVideoChatSession).mockReturnValueOnce(pending.promise);
  render(view());
  create();
  fireEvent.click(screen.getByRole('button', { name: 'Leave lobby' }));
  await act(async () => pending.resolve(room));
  expect(screen.getByTestId('location').textContent).toBe('/elsewhere');
});
it('removes private draft and room state on logout without an anonymous fetch', async () => {
  const mounted = render(view());
  await screen.findByText(room.title);
  fireEvent.change(title(), { target: { value: 'Private draft' } });
  mounted.rerender(view(null));
  expect(screen.queryByDisplayValue('Private draft')).toBeNull();
  expect(screen.queryByText(room.title)).toBeNull();
  expect(listVideoChatSessions).toHaveBeenCalledTimes(1);
});
it.each(['resolve', 'reject'] as const)(
  'preserves the newer list after an old locale read %s',
  async (finish) => {
    const pending = deferred<ReturnType<typeof response>>();
    vi.mocked(listVideoChatSessions).mockReturnValueOnce(pending.promise);
    const mounted = render(view());
    translation.t = (key: string) => key;
    mounted.rerender(view());
    await screen.findByText(room.title);
    await act(async () =>
      finish === 'resolve'
        ? pending.resolve(response([{ ...room, title: 'Old list' }]))
        : pending.reject(new Error('Old list failed')),
    );
    expect(screen.getByText(room.title)).toBeTruthy();
    expect(screen.queryByText('Old list')).toBeNull();
    expect(screen.queryByText('Old list failed')).toBeNull();
  },
);
it('keeps the normal lobby usable in StrictMode', async () => {
  render(view('current-session', true));
  await screen.findByText(room.title);
  await act(async () => create());
  expect(createVideoChatSession).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('location').textContent).toBe(
    '/apps/video-chat/sessions/room-one',
  );
});
it('copies the canonical same-origin invite without requesting a join credential', async () => {
  render(view());
  await screen.findByText(room.title);
  await act(async () =>
    fireEvent.click(
      screen.getByRole('button', { name: 'apps:videoChat.copyInvite' }),
    ),
  );
  expect(window.navigator.clipboard.writeText).toHaveBeenCalledExactlyOnceWith(
    `${window.location.origin}/apps/video-chat/sessions/room-one`,
  );
  expect(screen.getByText('apps:videoChat.copied')).toBeTruthy();
  expect(createVideoChatSession).not.toHaveBeenCalled();
});
it('drops a pending clipboard completion after a session replacement', async () => {
  const pending = deferred<void>();
  vi.mocked(window.navigator.clipboard.writeText).mockReturnValueOnce(
    pending.promise,
  );
  const mounted = render(view('old-session'));
  await screen.findByText(room.title);
  fireEvent.click(
    screen.getByRole('button', { name: 'apps:videoChat.copyInvite' }),
  );
  mounted.rerender(view('new-session'));
  await screen.findByText(room.title);
  await act(async () => pending.resolve());
  expect(screen.queryByText('apps:videoChat.copied')).toBeNull();
});
it('cleans its copied-label timeout when the lobby is removed', async () => {
  const mounted = render(view());
  await screen.findByText(room.title);
  vi.useFakeTimers();
  await act(async () =>
    fireEvent.click(
      screen.getByRole('button', { name: 'apps:videoChat.copyInvite' }),
    ),
  );
  expect(vi.getTimerCount()).toBe(1);
  mounted.unmount();
  expect(vi.getTimerCount()).toBe(0);
});
