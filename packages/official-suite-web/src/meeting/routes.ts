import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const MeetingView = lazy(() =>
  import('./views/MeetingView/MeetingView').then((module) => ({
    default: module.MeetingView,
  })),
);
const MeetingDetailView = lazy(() =>
  import('./views/MeetingView/MeetingDetailView').then((module) => ({
    default: module.MeetingDetailView,
  })),
);

export const meetingAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'meeting',
    chrome: getAppRouteChrome('meeting.root'),
    path: getAppRoutePattern('meeting.root'),
    element: lazyRoute(createElement(MeetingView)),
  },
  {
    appId: 'meeting',
    chrome: getAppRouteChrome('meeting.detail'),
    path: getAppRoutePattern('meeting.detail'),
    element: lazyRoute(createElement(MeetingDetailView)),
  },
];
