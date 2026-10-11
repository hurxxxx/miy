import { expect, it, vi } from 'vitest';
import * as oldModule from './index';
import * as module from '@miy/official-suite-web/planner/module';
import * as oldPublic from './public-api';
import * as publicApi from '@miy/official-suite-web/planner/public-api';
import * as existingApi from '@miy/official-suite-web/planner/api/planner-api';
import * as oldCalendar from '@/src/platform/calendar/calendar-api';
import * as calendar from '@miy/official-suite-web/calendar/calendar-api';
import * as oldEvents from '@/src/platform/calendar/calendar-events-changed';
import * as events from '@miy/official-suite-web/calendar/calendar-events-changed';
import { UnifiedCalendar as oldCalendarView } from '@/src/components/calendar/UnifiedCalendar';
import { UnifiedCalendar } from '@miy/official-suite-web/calendar/UnifiedCalendar';
import { getKoreanHolidayNames as oldHoliday } from '@/src/lib/korean-holidays';
import { getKoreanHolidayNames } from '@miy/platform-web/time/korean-holidays';
import * as oldFloating from '@/src/platform/personal-widgets/floating-panel-events';
import * as floating from '@miy/platform-web/personal-widgets/floating-panel-events';
import * as oldColors from '@/src/platform/theme/app-color-fallbacks';
import * as colors from '@miy/platform-web/theme/app-color-fallbacks';
import { plannerMessages } from '@miy/official-suite-web/planner/messages';
import { resources } from '@/src/platform/i18n/resources';

vi.mock('@miy/official-suite-web/planner/views/PlannerView', () => {
  throw new Error('eager Planner screen');
});
vi.mock(
  '@miy/official-suite-web/meeting/views/MeetingView/MeetingDetailLayout',
  () => {
    throw new Error('eager Meeting detail');
  },
);

it('keeps the exact module, narrow API, calendar and shared public objects', () => {
  for (const [old, owner] of [
    [oldModule, module],
    [oldPublic, publicApi],
    [publicApi, existingApi],
    [oldCalendar, calendar],
    [oldEvents, events],
    [oldFloating, floating],
    [oldColors, colors],
  ] as const) {
    expect(Object.keys(old).sort()).toEqual(Object.keys(owner).sort());
    for (const [key, value] of Object.entries(old))
      expect((owner as Record<string, unknown>)[key]).toBe(value);
  }
  expect(oldCalendarView).toBe(UnifiedCalendar);
  expect(oldHoliday).toBe(getKoreanHolidayNames);
  expect(new oldPublic.PlannerApiError(403, 'synthetic')).toBeInstanceOf(
    existingApi.PlannerApiError,
  );
});

it('retains one holiday warning cache through old and owned entries', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  try {
    expect(oldHoliday(2099, 0, 1)).toBeNull();
    expect(getKoreanHolidayNames(2099, 0, 1)).toBeNull();
    expect(warn).toHaveBeenCalledTimes(1);
  } finally {
    warn.mockRestore();
  }
});

it('composes identical owned Planner catalogs at the roots', () => {
  for (const locale of ['ko-KR', 'en-US'] as const)
    expect(resources[locale].apps.planner).toBe(plannerMessages[locale]);
});
