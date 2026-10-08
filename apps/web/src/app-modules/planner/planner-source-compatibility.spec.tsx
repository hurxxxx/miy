import { expect, it } from 'vitest';
import {
  PlannerApiError as SuiteError,
  PlannerEventModal as SuiteModal,
  listPlannerEvents as suiteList,
} from '@miy/official-suite-web/planner';
import {
  DateInput as SharedDateInput,
  DateTimeInput as SharedDateTimeInput,
} from '@miy/platform-web/date/DateInput';
import { addLocalCalendarDays as sharedAddDays } from '@miy/platform-web/time/native-date-input';
import { DateInput, DateTimeInput } from '@/src/components/date/DateInput';
import { addLocalCalendarDays } from '@/src/platform/time/native-date-input';
import { PlannerApiError, listPlannerEvents } from './public-api';
import { PlannerEventModal } from './views/PlannerEventModal';

it('keeps old API/error, editor and shared date entries as the exact same implementations', () => {
  expect(PlannerApiError).toBe(SuiteError);
  expect(listPlannerEvents).toBe(suiteList);
  expect(PlannerEventModal).toBe(SuiteModal);
  expect(DateInput).toBe(SharedDateInput);
  expect(DateTimeInput).toBe(SharedDateTimeInput);
  expect(addLocalCalendarDays).toBe(sharedAddDays);
});
