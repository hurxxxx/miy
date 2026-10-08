import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const RecordingView = lazy(() =>
  import('./views/RecordingView').then((module) => ({
    default: module.RecordingView,
  })),
);
const RecordingDetailView = lazy(() =>
  import('./views/RecordingDetailView').then((module) => ({
    default: module.RecordingDetailView,
  })),
);

export const recordingAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'recording',
    chrome: getAppRouteChrome('recording.root'),
    path: getAppRoutePattern('recording.root'),
    element: lazyRoute(createElement(RecordingView)),
  },
  {
    appId: 'recording',
    chrome: getAppRouteChrome('recording.detail'),
    path: getAppRoutePattern('recording.detail'),
    element: lazyRoute(createElement(RecordingDetailView)),
  },
];
