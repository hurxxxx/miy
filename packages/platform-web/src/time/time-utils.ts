import { readStoredDateFormatPreference } from './date-format-preference-store.js';
import { readStoredTimeZonePreference } from './time-zone-preference-store.js';
import {
  formatDateOnlyWithPreference,
  formatDateTimeWithPreference,
  formatRelativeTimeWithPreference,
  normalizeDateFormatPreference,
  normalizeTimeZone,
  type DateFormatPreference,
  type RelativeTimeOptions,
  type TemporalInput,
  type ZonedFormatOptions,
} from './zoned-date-formatter.js';

export {
  DATE_FORMAT_STORAGE_KEY,
  readStoredDateFormatPreference,
  syncDateFormatPreference,
} from './date-format-preference-store.js';
export {
  readStoredTimeZonePreference,
  syncTimeZonePreference,
  TIME_ZONE_STORAGE_KEY,
} from './time-zone-preference-store.js';
export {
  DATE_DISPLAY_LOCALE,
  DATE_FORMAT_OPTIONS,
  DEFAULT_TIME_ZONE,
  diffDateOnlyDays,
  getZonedDateParts,
  isSameDateInTimeZone,
  normalizeDateFormatPreference,
  normalizeTimeZone,
  parseApiDateTime,
  parseDateOnlyParts,
  TIME_ZONE_OPTIONS,
  zonedDateKey,
} from './zoned-date-formatter.js';
export type {
  DateFormatPreference,
  RelativeTimeOptions,
  TemporalInput,
  ZonedFormatOptions,
} from './zoned-date-formatter.js';

function resolveDateFormat(
  value: string | null | undefined,
): DateFormatPreference {
  return value === null || value === undefined
    ? readStoredDateFormatPreference()
    : normalizeDateFormatPreference(value);
}

function resolveTimeZone(value: string | null | undefined): string {
  return value === null || value === undefined
    ? readStoredTimeZonePreference()
    : normalizeTimeZone(value);
}

export function formatDateOnly(
  value: string | null | undefined,
  options: ZonedFormatOptions = {},
): string {
  return formatDateOnlyWithPreference(value, {
    ...options,
    dateFormat: resolveDateFormat(options.dateFormat),
  });
}

export function formatDateTime(
  value: TemporalInput,
  options: ZonedFormatOptions = {},
): string {
  return formatDateTimeWithPreference(value, {
    ...options,
    dateFormat: resolveDateFormat(options.dateFormat),
    timeZone: resolveTimeZone(options.timeZone),
  });
}

export function formatRelativeTime(
  value: TemporalInput,
  options: RelativeTimeOptions = {},
): string {
  return formatRelativeTimeWithPreference(value, {
    ...options,
    dateFormat: resolveDateFormat(options.dateFormat),
    timeZone: resolveTimeZone(options.timeZone),
  });
}
