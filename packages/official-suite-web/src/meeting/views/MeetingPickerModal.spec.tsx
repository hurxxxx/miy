import type * as PlatformPickers from '@miy/platform-web/pickers';
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
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AppBootstrapProvider } from '@miy/platform-web/apps';
import type { AppsBootstrapResponse } from '@miy/platform-web/apps/bootstrap-types';
import { listMeetings, type MeetingListItem } from '../api/meeting-api';
import {
  MeetingPickerModal,
  type MeetingPickerModalProps,
} from './MeetingPickerModal';

const dialog = vi.hoisted(() => ({
  lastPick: null as ((item: MeetingListItem) => void) | null,
  lastClose: null as (() => void) | null,
}));
vi.mock('@miy/platform-web/pickers', async (original) => {
  const actual = await original<typeof PlatformPickers>();
  return {
    ...actual,
    ResourcePickerDialog: (
      props: PlatformPickers.ResourcePickerDialogProps<MeetingListItem>,
    ) => {
      dialog.lastPick = props.onPick;
      dialog.lastClose = props.onClose;
      return <actual.ResourcePickerDialog {...props} />;
    },
  };
});
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en-US' },
  }),
}));
vi.mock('../api/meeting-api', async (original) => ({
  ...(await original<typeof import('../api/meeting-api')>()),
  listMeetings: vi.fn(),
}));
const meeting: MeetingListItem = {
  id: 'meeting-one',
  title: 'Current meeting',
  organizer_id: 'owner',
  organizer_name: 'Owner',
  start_at: '2026-10-07T10:00:00',
  end_at: '2026-10-07T11:00:00',
  status: 'scheduled',
  attendee_count: 1,
  task_link_count: 0,
  doc_link_count: 0,
};
const response = (items = [meeting]) => ({ items, total: items.length });
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function view({
  token = 'owner-session',
  userId = 'owner',
  admitted = true,
  open = true,
  onPick = vi.fn(),
  onClose = vi.fn(),
  excluded = [] as string[],
  strict = false,
}: Partial<{
  token: string | null;
  userId: string;
  admitted: boolean;
  open: boolean;
  onPick: MeetingPickerModalProps['onPick'];
  onClose: () => void;
  excluded: string[];
  strict: boolean;
}> = {}) {
  const content = (
    <AuthContext.Provider
      value={
        { token, user: { id: userId, time_zone: 'UTC' } } as AuthContextValue
      }
    >
      <AppBootstrapProvider
        value={{
          data: {
            apps: [{ app_id: 'meeting', enabled: admitted }],
          } as AppsBootstrapResponse,
          error: null,
          loading: false,
          reload: () => undefined,
        }}
      >
        <MeetingPickerModal
          isOpen={open}
          onClose={onClose}
          onPick={onPick}
          excludeMeetingIds={excluded}
        />
      </AppBootstrapProvider>
    </AuthContext.Provider>
  );
  return strict ? <StrictMode>{content}</StrictMode> : content;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listMeetings).mockReset().mockResolvedValue(response());
});
afterEach(cleanup);

it('lists admitted meetings and invokes the existing callback only after selection', async () => {
  const onPick = vi.fn();
  const onClose = vi.fn();
  render(view({ onPick, onClose, strict: true }));
  await screen.findByText(meeting.title);
  expect(listMeetings).toHaveBeenCalledWith('owner-session', { scope: 'all' });
  expect(onPick).not.toHaveBeenCalled();
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Current meeting/ })),
  );
  expect(onPick).toHaveBeenCalledExactlyOnceWith(meeting);
  expect(onClose).toHaveBeenCalledOnce();
});
it('does not fetch when Meeting admission is denied', () => {
  render(view({ admitted: false }));
  expect(screen.getByRole('alert').textContent).toContain(
    'accessNotice.blockedAction',
  );
  expect(listMeetings).not.toHaveBeenCalled();
});
it.each(['resolve', 'reject'] as const)(
  'discards an old list %s after the login changes',
  async (completion) => {
    const pending = deferred<ReturnType<typeof response>>();
    vi.mocked(listMeetings).mockReturnValueOnce(pending.promise);
    const mounted = render(view());
    mounted.rerender(view({ token: 'new-session' }));
    await screen.findByText(meeting.title);
    await act(async () =>
      completion === 'resolve'
        ? pending.resolve(
            response([{ ...meeting, title: 'Private old meeting' }]),
          )
        : pending.reject(new Error('Old list error')),
    );
    expect(screen.queryByText('Private old meeting')).toBeNull();
    expect(screen.queryByText('Old list error')).toBeNull();
    expect(screen.getByText(meeting.title)).toBeTruthy();
  },
);
it.each(['login', 'external-close', 'admission'] as const)(
  'does not close a new picker when an old pick completes after %s',
  async (change) => {
    const pending = deferred<void>();
    const onPick = vi.fn().mockReturnValueOnce(pending.promise);
    const onClose = vi.fn();
    const mounted = render(view({ onPick, onClose }));
    await screen.findByText(meeting.title);
    fireEvent.click(screen.getByRole('button', { name: /Current meeting/ }));
    if (change === 'login')
      mounted.rerender(view({ token: 'new-session', onPick, onClose }));
    else {
      mounted.rerender(
        view({
          open: change !== 'external-close',
          admitted: change !== 'admission',
          onPick,
          onClose,
        }),
      );
      mounted.rerender(view({ onPick, onClose }));
    }
    await screen.findByText(meeting.title);
    fireEvent.change(
      screen.getByRole('textbox', { name: 'common:actions.search' }),
      { target: { value: 'Current' } },
    );
    await act(async () => pending.resolve());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('Current')).toBeTruthy();
  },
);
it('does not display an old pick failure after a login change', async () => {
  const pending = deferred<void>();
  const onPick = vi.fn().mockReturnValueOnce(pending.promise);
  const mounted = render(view({ onPick }));
  await screen.findByText(meeting.title);
  fireEvent.click(screen.getByRole('button', { name: /Current meeting/ }));
  mounted.rerender(view({ token: 'new-session', onPick }));
  await act(async () => pending.reject(new Error('Old attach failure')));
  expect(screen.queryByText('Old attach failure')).toBeNull();
});
it('preserves search, exclusion and API error display', async () => {
  vi.mocked(listMeetings).mockResolvedValue(
    response([
      meeting,
      { ...meeting, id: 'excluded', title: 'Excluded meeting' },
    ]),
  );
  const mounted = render(view({ excluded: ['excluded'] }));
  await screen.findByText(meeting.title);
  expect(screen.queryByText('Excluded meeting')).toBeNull();
  fireEvent.change(
    screen.getByRole('textbox', { name: 'common:actions.search' }),
    { target: { value: 'no match' } },
  );
  expect(screen.getByText('recording.detail.meetingPicker.empty')).toBeTruthy();
  vi.mocked(listMeetings).mockRejectedValueOnce(
    new Error('Meeting access expired'),
  );
  mounted.rerender(view({ token: 'next-session' }));
  await screen.findByText('Meeting access expired');
});

it('does not fetch or retain a selectable list after logout', async () => {
  const mounted = render(view());
  await screen.findByText(meeting.title);
  const reads = vi.mocked(listMeetings).mock.calls.length;
  mounted.rerender(view({ token: null }));
  expect(screen.queryByText(meeting.title)).toBeNull();
  expect(listMeetings).toHaveBeenCalledTimes(reads);
});
it('rejects retained selection and close callbacks after its session unmounts', async () => {
  const onPick = vi.fn();
  const onClose = vi.fn();
  const mounted = render(view({ onPick, onClose }));
  await screen.findByText(meeting.title);
  const pick = dialog.lastPick;
  const close = dialog.lastClose;
  expect(pick).toBeTypeOf('function');
  expect(close).toBeTypeOf('function');
  mounted.rerender(view({ open: false, onPick, onClose }));
  await act(async () => {
    pick?.(meeting);
    close?.();
  });
  expect(onPick).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
});
it('clears the previous user session even when the token string is unchanged', async () => {
  const pending = deferred<void>();
  const onPick = vi.fn().mockReturnValue(pending.promise);
  const onClose = vi.fn();
  const mounted = render(view({ onPick, onClose }));
  await screen.findByText(meeting.title);
  fireEvent.click(screen.getByRole('button', { name: /Current meeting/ }));
  mounted.rerender(view({ userId: 'another-owner', onPick, onClose }));
  await act(async () => pending.resolve());
  expect(onClose).not.toHaveBeenCalled();
});
