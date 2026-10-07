import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const VideoChatView = lazy(() =>
  import('./views/VideoChatView').then((module) => ({
    default: module.VideoChatView,
  })),
);
const VideoChatRoomPage = lazy(() =>
  import('./views/VideoChatRoomPage').then((module) => ({
    default: module.VideoChatRoomPage,
  })),
);

export const videoChatAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'video-chat',
    chrome: getAppRouteChrome('video-chat.root'),
    path: getAppRoutePattern('video-chat.root'),
    element: lazyRoute(createElement(VideoChatView)),
  },
  {
    appId: 'video-chat',
    chrome: getAppRouteChrome('video-chat.session'),
    path: getAppRoutePattern('video-chat.session'),
    element: lazyRoute(createElement(VideoChatRoomPage)),
  },
];
