import { expect, it } from 'vitest';
import * as auth from '@miy/platform-web/auth-api';
import * as oldAuth from '@/src/platform/auth/auth-api';
import * as media from '@miy/platform-web/media';
import * as oldMedia from '@/src/platform/media/media-api';
import { useMediaUpload as oldUpload } from '@/src/platform/media/use-media-upload';
import { createMediaUrlResolutionSession as oldSession } from '@/src/platform/media/media-url-resolution-session';
import * as date from '@miy/platform-web/date/UserDateTime';
import * as oldDate from '@/src/components/date/UserDateTime';
import * as editor from '@miy/official-suite-web/community/editor';
import * as oldEditor from '@/src/platform/community/CommunityMarkdownEditor';
import * as events from '@miy/official-suite-web/community/events';
import * as oldEvents from '@/src/platform/community/community-channel-events';
import * as community from '@miy/official-suite-web/community';
import * as oldCommunity from './api/community-api';
import { i18n, syncLocale } from '@miy/platform-web/i18n';
import { i18n as oldI18n, syncLocale as oldSync } from '@/src/platform/i18n';
import { resources } from '@/src/platform/i18n/resources';
import { platformMessages } from '@miy/platform-web/i18n/resources';
import { communityMessages } from '@miy/official-suite-web/community/messages';

it('retains the exact common API/error/media/date objects through compatibility entries', () => {
  for (const [old, owned] of [
    [oldAuth, auth],
    [oldMedia, media],
    [oldDate, date],
  ] as const)
    for (const [key, value] of Object.entries(old))
      expect((owned as Record<string, unknown>)[key]).toBe(value);
  expect(new oldAuth.AuthApiError(401, 'synthetic')).toBeInstanceOf(
    auth.AuthApiError,
  );
  expect(oldUpload).toBe(media.useMediaUpload);
  expect(oldSession).toBe(media.createMediaUrlResolutionSession);
});

it('keeps one Community API/cache, editor and event implementation', () => {
  for (const [old, owned] of [
    [oldCommunity, community],
    [oldEditor, editor],
    [oldEvents, events],
  ] as const)
    for (const [key, value] of Object.entries(old))
      expect((owned as Record<string, unknown>)[key]).toBe(value);
  expect(new oldCommunity.CommunityApiError(403, 'synthetic')).toBeInstanceOf(
    community.CommunityApiError,
  );
});

it('composes owner catalogs into the existing singleton without copying message objects', () => {
  expect(oldI18n).toBe(i18n);
  expect(oldSync).toBe(syncLocale);
  for (const locale of ['ko-KR', 'en-US'] as const) {
    expect(resources[locale].common).toBe(platformMessages[locale].common);
    expect(resources[locale].auth).toBe(platformMessages[locale].auth);
    expect(resources[locale].apps.community).toBe(communityMessages[locale]);
  }
});
