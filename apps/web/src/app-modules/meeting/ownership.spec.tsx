import { expect, it, vi } from 'vitest';
import * as oldModule from './index';
import * as module from '@miy/official-suite-web/meeting/module';
import * as oldPublic from './public-api';
import * as publicApi from '@miy/official-suite-web/meeting/public-api';
import * as oldApi from './api/meeting-api';
import * as existingApi from '@miy/official-suite-web/meeting';
import {
  FormDialog as oldForm,
  FormFieldRow as oldField,
} from '@/src/components/form/FormDialog';
import { FormDialog, FormFieldRow } from '@miy/platform-web/form/FormDialog';
import { useRemoteUserSearchSession as oldSearch } from '@/src/platform/users/remote-user-search-session';
import { useRemoteUserSearchSession } from '@miy/platform-web/users/remote-user-search-session';
import { meetingMessages } from '@miy/official-suite-web/meeting/messages';
import { resources } from '@/src/platform/i18n/resources';

vi.mock(
  '@miy/official-suite-web/meeting/views/MeetingView/MeetingCreateModal',
  () => {
    throw new Error('eager Meeting creator');
  },
);
vi.mock(
  '@miy/official-suite-web/meeting/views/MeetingView/MeetingDetailLayout',
  () => {
    throw new Error('eager Meeting layout');
  },
);

it('keeps exact module/public/API keys, lazy wrappers and error objects', () => {
  for (const [old, owner] of [
    [oldModule, module],
    [oldPublic, publicApi],
    [oldApi, existingApi],
  ] as const) {
    expect(Object.keys(old).sort()).toEqual(Object.keys(owner).sort());
    for (const [key, value] of Object.entries(old))
      expect((owner as Record<string, unknown>)[key]).toBe(value);
  }
  expect(oldModule.MeetingCreateModal).toBe(module.MeetingCreateModal);
  expect(oldModule.MeetingDetailLayout).toBe(module.MeetingDetailLayout);
  expect(new oldApi.MeetingApiError(403, 'synthetic')).toBeInstanceOf(
    existingApi.MeetingApiError,
  );
});
it('keeps the existing form and request-session implementation objects', () => {
  expect(oldForm).toBe(FormDialog);
  expect(oldField).toBe(FormFieldRow);
  expect(oldSearch).toBe(useRemoteUserSearchSession);
});
it('composes the same owned Meeting catalogs at the roots', () => {
  for (const locale of ['ko-KR', 'en-US'] as const)
    expect(resources[locale].apps.meeting).toBe(meetingMessages[locale]);
});
