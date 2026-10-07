import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { Video } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const videoChatManifest: AppModuleManifest = {
  appBarItem: { id: 'video-chat', title: 'video-chat', icon: Video },
  contract: {
    owner: 'video-chat-platform',
    permissions: [],
    apiDomain: 'video_chat',
    aiCapabilities: [],
    writeAuditActions: [],
    appLocalTests: [
      'apps/api/tests/test_video_chat.py',
      'packages/official-suite-web/src/video-chat/api/video-chat-api.spec.ts',
      'packages/official-suite-web/src/video-chat/views/VideoChatView.spec.tsx',
      'packages/official-suite-web/src/video-chat/views/VideoChatRoomPage.spec.tsx',
      'apps/web/src/app-modules/video-chat/ownership.spec.tsx',
      'apps/web/src/app-modules/video-chat/video-chat-source-compatibility.spec.tsx',
    ],
  },
  defaultActiveNavItemId: 'video-chat-room',
  navItems: [
    {
      id: 'video-chat-room',
      title: 'video-chat-room',
      icon: Video,
      category: 'Meetings',
      appId: 'video-chat',
    },
  ],
  appRoutePaths: [
    getAppRoutePattern('video-chat.root'),
    getAppRoutePattern('video-chat.session'),
  ],
};
