import { type ReactNode, StrictMode, useEffect } from 'react';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  createVideoChatJoinToken,
  endVideoChatSession,
  type VideoChatJoinTokenResponse,
  type VideoChatSession,
} from '../api/video-chat-api';
import { VideoChatRoomPage } from './VideoChatRoomPage';

const evidence = vi.hoisted(() => ({
  connections: [] as string[],
  disconnections: [] as string[],
}));
const translation = vi.hoisted(() => ({
  t: (key: string) => key,
  i18n: { language: 'en-US' },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => translation }));
vi.mock('../api/video-chat-api', () => ({
  createVideoChatJoinToken: vi.fn(),
  endVideoChatSession: vi.fn(),
  startVideoChatCaptions: vi.fn(),
  startVideoChatRecording: vi.fn(),
  stopVideoChatCaptions: vi.fn(),
  stopVideoChatRecording: vi.fn(),
}));
// An inert React connection probe. No LiveKit server, devices or customer
// credentials are used; real SDK styles and the production import stay intact.
vi.mock('@livekit/components-react', () => ({
  LiveKitRoom: ({ token }: { token: string }) => {
    useEffect(() => {
      evidence.connections.push(token);
      return () => {
        evidence.disconnections.push(token);
      };
    }, [token]);
    return <output data-testid="synthetic-room">{token}</output>;
  },
}));
const room: VideoChatSession = {
  id: 'room-one',
  meeting_id: null,
  room_name: 'synthetic-room',
  title: 'Synthetic room',
  status: 'open',
  provider: 'livekit',
  started_by_id: 'owner',
  started_by_name: 'Owner',
  started_at: '2026-10-07T09:00:00Z',
  ended_at: null,
  recording_status: 'idle',
  recording_egress_id: null,
  recording_id: null,
  captions_status: 'off',
  captions_started_at: null,
  captions_ended_at: null,
  created_at: '2026-10-07T09:00:00Z',
  updated_at: '2026-10-07T09:00:00Z',
};
function response(token: string, id = room.id): VideoChatJoinTokenResponse {
  return {
    session: { ...room, id },
    token,
    livekit_url: 'wss://synthetic.invalid',
    identity: 'owner',
    display_name: 'Owner',
    expires_at: '2026-10-07T09:05:00Z',
  };
}
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
      <button onClick={() => navigate('/apps/video-chat/sessions/room-two')}>
        Switch room
      </button>
      <button onClick={() => navigate('/elsewhere')}>Leave room</button>
    </>
  );
}
function view(token: string | null = 'current-login', strict = false) {
  const content: ReactNode = (
    <AuthContext.Provider
      value={
        { token, user: { id: 'owner', time_zone: 'UTC' } } as AuthContextValue
      }
    >
      <MemoryRouter initialEntries={['/apps/video-chat/sessions/room-one']}>
        <Location />
        <Routes>
          <Route
            path="/apps/video-chat/sessions/:sessionId"
            element={<VideoChatRoomPage />}
          />
          <Route path="*" element={<div>Other view</div>} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>
  );
  return strict ? <StrictMode>{content}</StrictMode> : content;
}
beforeEach(() => {
  vi.clearAllMocks();
  evidence.connections.length = 0;
  evidence.disconnections.length = 0;
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('does not request a join credential without a current login', () => {
  render(view(null));
  expect(createVideoChatJoinToken).not.toHaveBeenCalled();
  expect(screen.queryByTestId('synthetic-room')).toBeNull();
});

it('cannot connect a late previous-login credential after the login changes', async () => {
  const old = deferred<VideoChatJoinTokenResponse>();
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken).mockImplementation((token) =>
    token === 'old-login' ? old.promise : current.promise,
  );
  const mounted = render(view('old-login'));
  mounted.rerender(view('new-login'));
  await act(async () => current.resolve(response('new-room-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'new-room-credential',
  );
  await act(async () => old.resolve(response('old-room-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'new-room-credential',
  );
  expect(evidence.connections).not.toContain('old-room-credential');
});

it('disconnects the previous login while its replacement join is pending', async () => {
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken).mockImplementation((token) =>
    token === 'old-login'
      ? Promise.resolve(response('old-room-credential'))
      : current.promise,
  );
  const mounted = render(view('old-login'));
  await act(async () => undefined);
  expect(screen.getByTestId('synthetic-room')).toBeTruthy();
  mounted.rerender(view('new-login'));
  expect(screen.queryByTestId('synthetic-room')).toBeNull();
  expect(evidence.disconnections).toContain('old-room-credential');
  await act(async () => current.resolve(response('new-room-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'new-room-credential',
  );
});

it('cannot connect a late prior-room credential after route replacement', async () => {
  const old = deferred<VideoChatJoinTokenResponse>();
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken).mockImplementation((_token, id) =>
    id === 'room-one' ? old.promise : current.promise,
  );
  render(view());
  fireEvent.click(screen.getByRole('button', { name: 'Switch room' }));
  await act(async () =>
    current.resolve(response('room-two-credential', 'room-two')),
  );
  await act(async () => old.resolve(response('room-one-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'room-two-credential',
  );
  expect(evidence.connections).not.toContain('room-one-credential');
});

it('keeps the latest join result through development StrictMode replay', async () => {
  const old = deferred<VideoChatJoinTokenResponse>();
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken)
    .mockImplementationOnce(() => old.promise)
    .mockImplementationOnce(() => current.promise);
  render(view('current-login', true));
  expect(createVideoChatJoinToken).toHaveBeenCalledTimes(2);
  await act(async () => current.resolve(response('latest-room-credential')));
  await act(async () => old.resolve(response('replayed-room-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'latest-room-credential',
  );
  expect(evidence.connections).not.toContain('replayed-room-credential');
});

it('ignores an older join error after the current response succeeds', async () => {
  const old = deferred<VideoChatJoinTokenResponse>();
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken)
    .mockImplementationOnce(() => old.promise)
    .mockImplementationOnce(() => current.promise);
  render(view('current-login', true));
  await act(async () => current.resolve(response('latest-room-credential')));
  await act(async () => old.reject(new Error('Obsolete room denial')));
  expect(screen.queryByText('Obsolete room denial')).toBeNull();
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'latest-room-credential',
  );
});

it('a pending end action cannot navigate back after the user leaves the room', async () => {
  const ended = deferred<VideoChatSession>();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.mocked(createVideoChatJoinToken).mockResolvedValue(
    response('room-credential'),
  );
  vi.mocked(endVideoChatSession).mockReturnValue(ended.promise);
  render(view());
  await act(async () => undefined);
  fireEvent.click(
    screen.getByRole('button', { name: 'apps:videoChat.endRoom' }),
  );
  expect(endVideoChatSession).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Leave room' }));
  await act(async () => ended.resolve({ ...room, status: 'ended' }));
  expect(screen.getByTestId('location').textContent).toBe('/elsewhere');
  expect(screen.queryByTestId('synthetic-room')).toBeNull();
});

it('a refused refresh cannot reconnect the obsolete join credential', async () => {
  vi.mocked(createVideoChatJoinToken)
    .mockResolvedValueOnce(response('obsolete-room-credential'))
    .mockRejectedValueOnce(new Error('Current room denied'));
  render(view());
  await act(async () => undefined);
  expect(screen.getByTestId('synthetic-room')).toBeTruthy();
  await act(async () => {
    fireEvent.click(screen.getByTitle('apps:videoChat.refresh'));
  });
  expect(screen.getByText('Current room denied')).toBeTruthy();
  expect(screen.queryByTestId('synthetic-room')).toBeNull();
  expect(evidence.connections).toEqual(['obsolete-room-credential']);
  expect(evidence.disconnections).toEqual(['obsolete-room-credential']);
});

it('an older join failure cannot finish the latest pending join', async () => {
  const old = deferred<VideoChatJoinTokenResponse>();
  const current = deferred<VideoChatJoinTokenResponse>();
  vi.mocked(createVideoChatJoinToken)
    .mockImplementationOnce(() => old.promise)
    .mockImplementationOnce(() => current.promise);
  render(view('current-login', true));
  await act(async () => old.reject(new Error('Obsolete room denial')));
  expect(
    (screen.getByTitle('apps:videoChat.refresh') as HTMLButtonElement).disabled,
  ).toBe(true);
  expect(screen.queryByText('Obsolete room denial')).toBeNull();
  await act(async () => current.resolve(response('current-room-credential')));
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'current-room-credential',
  );
});

it('an old action failure cannot affect the replacement login', async () => {
  const ended = deferred<VideoChatSession>();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.mocked(createVideoChatJoinToken).mockImplementation((token) =>
    Promise.resolve(
      response(
        token === 'old-login'
          ? 'old-room-credential'
          : 'current-room-credential',
      ),
    ),
  );
  vi.mocked(endVideoChatSession).mockReturnValue(ended.promise);
  const mounted = render(view('old-login'));
  await act(async () => undefined);
  fireEvent.click(
    screen.getByRole('button', { name: 'apps:videoChat.endRoom' }),
  );
  mounted.rerender(view('current-login'));
  await act(async () => ended.reject(new Error('Obsolete action denial')));
  expect(screen.queryByText('Obsolete action denial')).toBeNull();
  expect(screen.getByTestId('synthetic-room').textContent).toBe(
    'current-room-credential',
  );
  expect(screen.getByTestId('location').textContent).toBe(
    '/apps/video-chat/sessions/room-one',
  );
});
