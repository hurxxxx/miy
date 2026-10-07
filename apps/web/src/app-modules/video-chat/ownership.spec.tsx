import { expect, it } from 'vitest';
import * as owner from '@miy/official-suite-web/video-chat/module';
import { videoChatMessages } from '@miy/official-suite-web/video-chat/messages';
import { VideoChatRoomPage as ownedRoom } from '@miy/official-suite-web/video-chat/views/VideoChatRoomPage';
import { resources } from '@/src/platform/i18n/resources';
import {
  videoChatModule,
  videoChatManifest,
  videoChatAppRoutes,
} from './index';
import { VideoChatRoomPage } from './views/VideoChatRoomPage';

it('keeps module, manifest and lazy routes on the same official owner objects', () => {
  expect(videoChatModule).toBe(owner.videoChatModule);
  expect(videoChatManifest).toBe(owner.videoChatManifest);
  expect(videoChatAppRoutes).toBe(owner.videoChatAppRoutes);
  expect(videoChatAppRoutes.map(({ path }) => path)).toEqual([
    '/apps/video-chat',
    '/apps/video-chat/sessions/:sessionId',
  ]);
});

it('keeps the legacy room on the exact owned runtime', () => {
  expect(VideoChatRoomPage).toBe(ownedRoom);
});

it.each(['ko-KR', 'en-US'] as const)(
  'composes unchanged %s Video Chat messages',
  (locale) => {
    expect(resources[locale].apps.videoChat).toBe(videoChatMessages[locale]);
  },
);
