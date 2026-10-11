import type * as PlatformPickers from '@miy/platform-web/pickers';
import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  AppBootstrapProvider,
  type AppsBootstrapResponse,
} from '@miy/platform-web/apps';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  listPmsTaskLists,
  listTaskListTasks,
  type PmsTask,
} from '../api/pms-api';
import { TaskPickerModal, type TaskPickerModalProps } from './TaskPickerModal';

const dialog = vi.hoisted(() => ({
  pick: null as ((item: PmsTask) => void) | null,
  close: null as (() => void) | null,
  t: (key: string) => key,
}));
vi.mock('@miy/platform-web/pickers', async (original) => {
  const actual = await original<typeof PlatformPickers>();
  return {
    ...actual,
    ResourcePickerDialog: (
      props: PlatformPickers.ResourcePickerDialogProps<PmsTask>,
    ) => {
      dialog.pick = props.onPick;
      dialog.close = props.onClose;
      return <actual.ResourcePickerDialog {...props} />;
    },
  };
});
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: dialog.t }) }));
vi.mock('../api/pms-api', async (original) => ({
  ...(await original<typeof import('../api/pms-api')>()),
  listPmsTaskLists: vi.fn(),
  listTaskListTasks: vi.fn(),
}));
const task = {
  id: 'task-one',
  title: 'Current task',
  reference: 'TASK-1',
  status_label: 'Open',
} as PmsTask;
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
  list = 'list-one' as string | null,
  onPick = vi.fn(),
  onClose = vi.fn(),
  excluded = [] as string[],
  strict = false,
}: Partial<{
  token: string | null;
  userId: string;
  admitted: boolean;
  open: boolean;
  list: string | null;
  onPick: TaskPickerModalProps['onPick'];
  onClose: () => void;
  excluded: string[];
  strict: boolean;
}> = {}) {
  const content = (
    <AuthContext.Provider
      value={{ token, user: { id: userId } } as AuthContextValue}
    >
      <AppBootstrapProvider
        value={{
          data: {
            apps: [{ app_id: 'pms', enabled: admitted }],
          } as AppsBootstrapResponse,
          error: null,
          loading: false,
          reload: () => undefined,
        }}
      >
        <TaskPickerModal
          isOpen={open}
          fixedTaskListId={list}
          onPick={onPick}
          onClose={onClose}
          excludeTaskIds={excluded}
        />
      </AppBootstrapProvider>
    </AuthContext.Provider>
  );
  return strict ? <StrictMode>{content}</StrictMode> : content;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTaskListTasks)
    .mockReset()
    .mockResolvedValue({ items: [task], total: 1 } as Awaited<
      ReturnType<typeof listTaskListTasks>
    >);
  vi.mocked(listPmsTaskLists)
    .mockReset()
    .mockResolvedValue({
      items: [{ id: 'list-one', key: 'ONE', name: 'My list' }],
      total: 1,
    } as Awaited<ReturnType<typeof listPmsTaskLists>>);
});
afterEach(cleanup);
it('uses admitted list scope and the existing void callback after an explicit pick', async () => {
  const onPick = vi.fn(),
    onClose = vi.fn();
  render(view({ onPick, onClose, strict: true }));
  await screen.findByText(task.title);
  expect(listTaskListTasks).toHaveBeenCalledWith('owner-session', 'list-one', {
    archived_state: 'active',
    q: undefined,
  });
  expect(onPick).not.toHaveBeenCalled();
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Current task/ })),
  );
  expect(onPick).toHaveBeenCalledExactlyOnceWith(task);
  expect(onClose).toHaveBeenCalledOnce();
});
it.each(['denied', 'logout'] as const)('does not fetch for %s', (mode) => {
  render(
    view({
      admitted: mode !== 'denied',
      token: mode === 'logout' ? null : 'owner-session',
    }),
  );
  expect(listTaskListTasks).not.toHaveBeenCalled();
  expect(listPmsTaskLists).not.toHaveBeenCalled();
});
it.each(['login', 'user', 'close', 'admission', 'list', 'unmount'] as const)(
  'ignores a pending pick success after %s',
  async (change) => {
    const pending = deferred<void>(),
      onPick = vi.fn().mockReturnValue(pending.promise),
      onClose = vi.fn();
    const mounted = render(view({ onPick, onClose }));
    await screen.findByText(task.title);
    fireEvent.click(screen.getByRole('button', { name: /Current task/ }));
    if (change === 'unmount') mounted.unmount();
    else if (change === 'close' || change === 'admission') {
      mounted.rerender(
        view({
          onPick,
          onClose,
          open: change !== 'close',
          admitted: change !== 'admission',
        }),
      );
      mounted.rerender(view({ onPick, onClose }));
    } else
      mounted.rerender(
        view({
          onPick,
          onClose,
          token: change === 'login' ? 'new-session' : 'owner-session',
          userId: change === 'user' ? 'new-user' : 'owner',
          list: change === 'list' ? 'other-list' : 'list-one',
        }),
      );
    await act(async () => pending.resolve());
    expect(onClose).not.toHaveBeenCalled();
  },
);
it.each(['login', 'close', 'list'] as const)(
  'hides a pending pick failure after %s',
  async (change) => {
    const pending = deferred<void>(),
      onPick = vi.fn().mockReturnValue(pending.promise);
    const mounted = render(view({ onPick }));
    await screen.findByText(task.title);
    fireEvent.click(screen.getByRole('button', { name: /Current task/ }));
    if (change === 'close') {
      mounted.rerender(view({ onPick, open: false }));
      mounted.rerender(view({ onPick }));
    } else
      mounted.rerender(
        view({
          onPick,
          token: change === 'login' ? 'new-session' : 'owner-session',
          list: change === 'list' ? 'other-list' : 'list-one',
        }),
      );
    await act(async () => pending.reject(new Error('Old private error')));
    expect(screen.queryByText('Old private error')).toBeNull();
  },
);
it('does not submit or close through retained callbacks after unmount', async () => {
  const onPick = vi.fn(),
    onClose = vi.fn();
  const mounted = render(view({ onPick, onClose }));
  await screen.findByText(task.title);
  const pick = dialog.pick,
    close = dialog.close;
  mounted.unmount();
  await act(async () => {
    pick?.(task);
    close?.();
  });
  expect(onPick).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
});
it.each(['resolve', 'reject'] as const)(
  'discards an old task-list %s when login changes',
  async (completion) => {
    const pending = deferred<Awaited<ReturnType<typeof listTaskListTasks>>>();
    vi.mocked(listTaskListTasks).mockReturnValueOnce(pending.promise);
    const mounted = render(view());
    mounted.rerender(view({ token: 'new-session' }));
    await screen.findByText(task.title);
    await act(async () =>
      completion === 'resolve'
        ? pending.resolve({
            items: [{ ...task, title: 'Private previous task' }],
            total: 1,
          } as Awaited<ReturnType<typeof listTaskListTasks>>)
        : pending.reject(new Error('Private previous failure')),
    );
    expect(screen.queryByText('Private previous task')).toBeNull();
    expect(screen.queryByText('Private previous failure')).toBeNull();
  },
);
it('keeps a current failure visible for explicit retry', async () => {
  const onPick = vi
      .fn()
      .mockRejectedValueOnce(new Error('Current failure'))
      .mockResolvedValue(undefined),
    onClose = vi.fn();
  render(view({ onPick, onClose }));
  await screen.findByText(task.title);
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Current task/ })),
  );
  expect(screen.getByText('Current failure')).toBeTruthy();
  expect(onClose).not.toHaveBeenCalled();
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Current task/ })),
  );
  expect(onClose).toHaveBeenCalledOnce();
});
it('retains list selection, server query and exclusion contract', async () => {
  vi.mocked(listTaskListTasks).mockResolvedValue({
    items: [task, { ...task, id: 'excluded', title: 'Excluded task' }],
    total: 2,
  } as Awaited<ReturnType<typeof listTaskListTasks>>);
  render(view({ list: null, excluded: ['excluded'] }));
  await screen.findByText(task.title);
  expect(screen.queryByText('Excluded task')).toBeNull();
  fireEvent.change(
    screen.getByRole('textbox', { name: 'common:actions.search' }),
    { target: { value: ' current ' } },
  );
  await act(async () => Promise.resolve());
  expect(listTaskListTasks).toHaveBeenLastCalledWith(
    'owner-session',
    'list-one',
    { archived_state: 'active', q: 'current' },
  );
});
it('allows a new list selection while the old list pick is pending', async () => {
  const pending = deferred<void>();
  const onPick = vi
      .fn()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue(undefined),
    onClose = vi.fn();
  vi.mocked(listPmsTaskLists).mockResolvedValue({
    items: [
      { id: 'list-one', key: 'ONE', name: 'First' },
      { id: 'list-two', key: 'TWO', name: 'Second' },
    ],
    total: 2,
  } as Awaited<ReturnType<typeof listPmsTaskLists>>);
  render(view({ list: null, onPick, onClose }));
  await screen.findByText(task.title);
  fireEvent.click(screen.getByRole('button', { name: /Current task/ }));
  fireEvent.change(screen.getByRole('combobox'), {
    target: { value: 'list-two' },
  });
  await act(async () => Promise.resolve());
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Current task/ })),
  );
  expect(onPick).toHaveBeenCalledTimes(2);
  expect(onClose).toHaveBeenCalledOnce();
  await act(async () => pending.resolve());
  expect(onClose).toHaveBeenCalledOnce();
});
it('does not reuse callbacks immediately after the user closes the picker', async () => {
  const onPick = vi.fn(),
    onClose = vi.fn();
  render(view({ onPick, onClose }));
  await screen.findByText(task.title);
  const pick = dialog.pick,
    close = dialog.close;
  await act(async () => {
    close?.();
    pick?.(task);
    close?.();
  });
  expect(onPick).not.toHaveBeenCalled();
  expect(onClose).toHaveBeenCalledOnce();
});
