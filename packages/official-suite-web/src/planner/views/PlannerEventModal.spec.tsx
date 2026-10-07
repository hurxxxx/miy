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
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import {
  createPlannerEvent,
  deletePlannerEvent,
  getPlannerEvent,
  updatePlannerEvent,
  type PlannerEvent,
} from '../api/planner-api';
import { PlannerEventModal } from './PlannerEventModal';

const translation = vi.hoisted(() => ({
  t: (key: string) => key,
  i18n: { language: 'en-US', resolvedLanguage: 'en-US' },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => translation }));
vi.mock('../api/planner-api', async (original) => ({
  ...(await original<typeof import('../api/planner-api')>()),
  createPlannerEvent: vi.fn(),
  deletePlannerEvent: vi.fn(),
  getPlannerEvent: vi.fn(),
  updatePlannerEvent: vi.fn(),
}));

const event: PlannerEvent = {
  id: 'event-1',
  ownerId: 'owner-1',
  ownerName: 'Owner',
  title: 'Existing event',
  description: 'Notes',
  location: 'Room',
  timeZone: 'UTC',
  allDay: true,
  startHasTime: false,
  endHasTime: false,
  start: '2026-03-07',
  end: '2026-03-09',
  calendarStart: '2026-03-07',
  calendarEnd: '2026-03-09',
  calendarAllDay: true,
  createdAt: '2026-03-01T00:00:00Z',
  updatedAt: '2026-03-01T00:00:00Z',
};
const initialRange = {
  allDay: true,
  start: new Date(2026, 2, 7),
  end: new Date(2026, 2, 9),
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const callbacks = { onClose: vi.fn(), onSaved: vi.fn(), onDeleted: vi.fn() };
function view({
  token = 'first-session',
  open = true,
  eventId = null,
}: {
  token?: string | null;
  open?: boolean;
  eventId?: string | null;
} = {}) {
  return (
    <AuthContext.Provider value={{ token } as AuthContextValue}>
      <PlannerEventModal
        isOpen={open}
        eventId={eventId}
        initialRange={initialRange}
        {...callbacks}
      />
    </AuthContext.Provider>
  );
}
function enterTitle(title = 'New event') {
  fireEvent.change(
    screen.getByRole('textbox', { name: 'apps:planner.title' }),
    { target: { value: title } },
  );
}
function save() {
  fireEvent.click(screen.getByRole('button', { name: 'common:actions.save' }));
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getPlannerEvent).mockResolvedValue(event);
  vi.mocked(createPlannerEvent).mockResolvedValue(event);
  vi.mocked(updatePlannerEvent).mockResolvedValue(event);
  vi.mocked(deletePlannerEvent).mockResolvedValue();
});
afterEach(cleanup);

it('creates the selected date range with its exclusive end and current session', async () => {
  render(view());
  enterTitle();
  await act(async () => save());
  expect(createPlannerEvent).toHaveBeenCalledWith('first-session', {
    title: 'New event',
    description: '',
    location: '',
    allDay: true,
    start: '2026-03-07',
    end: '2026-03-09',
  });
  expect(callbacks.onSaved).toHaveBeenCalledWith(event);
});

it('loads and updates an existing event without changing its date-only contract', async () => {
  render(view({ eventId: event.id }));
  await screen.findByDisplayValue(event.title);
  enterTitle('Updated');
  await act(async () => save());
  expect(updatePlannerEvent).toHaveBeenCalledWith('first-session', event.id, {
    title: 'Updated',
    description: 'Notes',
    location: 'Room',
    allDay: true,
    start: '2026-03-07',
    end: '2026-03-09',
  });
  expect(callbacks.onSaved).toHaveBeenCalledWith(event);
});

it('deletes an existing event and reports only the selected ID', async () => {
  render(view({ eventId: event.id }));
  await screen.findByDisplayValue(event.title);
  await act(async () =>
    fireEvent.click(
      screen.getByRole('button', { name: 'common:actions.delete' }),
    ),
  );
  expect(deletePlannerEvent).toHaveBeenCalledWith('first-session', event.id);
  expect(callbacks.onDeleted).toHaveBeenCalledWith(event.id);
});

it('retains a failed save draft and allows an explicit retry', async () => {
  vi.mocked(createPlannerEvent).mockRejectedValueOnce(new Error('Save denied'));
  render(view());
  enterTitle('Keep this draft');
  await act(async () => save());
  expect(screen.getByRole('alert').textContent).toBe('Save denied');
  expect(screen.getByDisplayValue('Keep this draft')).toBeTruthy();
  expect(callbacks.onSaved).not.toHaveBeenCalled();
  await act(async () => save());
  expect(createPlannerEvent).toHaveBeenCalledTimes(2);
  expect(callbacks.onSaved).toHaveBeenCalledTimes(1);
});

it('does not deliver an earlier session save into the next session', async () => {
  const pending = deferred<PlannerEvent>();
  vi.mocked(createPlannerEvent).mockReturnValueOnce(pending.promise);
  const mounted = render(view());
  enterTitle('Private draft');
  save();
  mounted.rerender(view({ token: 'second-session' }));
  await act(async () => pending.resolve(event));
  expect(callbacks.onSaved).not.toHaveBeenCalled();
  expect(screen.queryByDisplayValue('Private draft')).toBeNull();
});

it('does not notify after a pending delete modal closes', async () => {
  const pending = deferred<void>();
  vi.mocked(deletePlannerEvent).mockReturnValueOnce(pending.promise);
  const mounted = render(view({ eventId: event.id }));
  await screen.findByDisplayValue(event.title);
  fireEvent.click(
    screen.getByRole('button', { name: 'common:actions.delete' }),
  );
  mounted.rerender(view({ eventId: event.id, open: false }));
  await act(async () => pending.resolve());
  expect(callbacks.onDeleted).not.toHaveBeenCalled();
});

it('clears a visible draft on logout', () => {
  const mounted = render(view());
  enterTitle('Private draft');
  mounted.rerender(view({ token: null }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByDisplayValue('Private draft')).toBeNull();
});

it('rejects an old event save callback after the editor selection changes', async () => {
  const pending = deferred<PlannerEvent>();
  vi.mocked(updatePlannerEvent).mockReturnValueOnce(pending.promise);
  const mounted = render(view({ eventId: event.id }));
  await screen.findByDisplayValue(event.title);
  save();
  mounted.rerender(view({ eventId: 'event-2' }));
  await act(async () => pending.resolve(event));
  expect(callbacks.onSaved).not.toHaveBeenCalled();
});
