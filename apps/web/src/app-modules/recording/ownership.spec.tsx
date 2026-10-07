import { expect, it, vi } from 'vitest';
import * as recording from '@miy/official-suite-web/recording';
import * as oldRecording from './public-api';
import * as api from '@miy/official-suite-web/recording/api/recording-api';
import * as oldApi from './api/recording-api';
import { RecordingRecorderRuntime } from '@miy/official-suite-web/recording/recorder/recording-recorder-runtime';
import { RecordingRecorderRuntime as oldRuntime } from './recorder/recording-recorder-runtime';
import { RecordingTusOffsetConflictError } from '@miy/official-suite-web/recording/recorder/recording-upload-session';
import { RecordingTusOffsetConflictError as OldConflict } from './recorder/recording-upload-session';
import picker, {
  TaskPickerModal,
} from '@miy/official-suite-web/recording/views/TaskPickerModal';
import oldPicker, {
  TaskPickerModal as OldPicker,
} from './views/TaskPickerModal';
import * as links from '@miy/platform-web/apps/app-links';
import * as oldLinks from '@/src/platform/apps/app-links';
import { runRequestsWithConcurrency } from '@miy/platform-web/network/request-concurrency';
import { runRequestsWithConcurrency as oldConcurrency } from '@/src/platform/network/request-concurrency';
import { getCoreShellSearchParams } from '@miy/core-web/shell-navigation';
import { getShellSearchParams } from '@/src/app-shell-navigation-model';
import { recordingMessages } from '@miy/official-suite-web/recording/messages';
import { resources } from '@/src/platform/i18n/resources';

vi.mock('@miy/official-suite-web/recording/views/LinkedRecordingsList', () => {
  throw new Error('eager linked-recording screen');
});

it('retains the public lazy API and actual recorder/error/default component objects', () => {
  for (const [old, owner] of [
    [oldRecording, recording],
    [oldApi, api],
  ] as const) {
    expect(Object.keys(old).sort()).toEqual(Object.keys(owner).sort());
    for (const [key, value] of Object.entries(old))
      expect((owner as Record<string, unknown>)[key]).toBe(value);
  }
  expect(new oldApi.RecordingApiError(403, 'synthetic')).toBeInstanceOf(
    api.RecordingApiError,
  );
  expect(oldRuntime).toBe(RecordingRecorderRuntime);
  expect(OldConflict).toBe(RecordingTusOffsetConflictError);
  expect(oldPicker).toBe(picker);
  expect(OldPicker).toBe(TaskPickerModal);
  expect(picker).toBe(TaskPickerModal);
});
it('shares the actual common route/concurrency implementations and root search helper', () => {
  for (const [key, value] of Object.entries(oldLinks))
    expect((links as Record<string, unknown>)[key]).toBe(value);
  expect(oldConcurrency).toBe(runRequestsWithConcurrency);
  expect(getShellSearchParams).toBe(getCoreShellSearchParams);
});
it('composes exactly the owned Recording catalogs into the existing root', () => {
  for (const locale of ['ko-KR', 'en-US'] as const)
    expect(resources[locale].apps.recording).toBe(recordingMessages[locale]);
});
