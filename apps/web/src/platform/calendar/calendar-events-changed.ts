export const CALENDAR_EVENTS_CHANGED_EVENT =
  'mty:calendar-events-changed';

export function dispatchCalendarEventsChanged(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new Event(CALENDAR_EVENTS_CHANGED_EVENT));
}
