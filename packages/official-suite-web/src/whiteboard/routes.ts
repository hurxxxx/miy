import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { StaticRouteDefinition } from '@miy/core-web/navigation-types';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const WhiteboardView = lazy(() =>
  import('./views/WhiteboardView').then((module) => ({
    default: module.WhiteboardView,
  })),
);

export const whiteboardToolElement = lazyRoute(createElement(WhiteboardView));

export const whiteboardAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'whiteboard',
    chrome: getAppRouteChrome('whiteboard.root'),
    path: getAppRoutePattern('whiteboard.root'),
    element: whiteboardToolElement,
  },
  {
    appId: 'whiteboard',
    chrome: getAppRouteChrome('whiteboard.board'),
    path: getAppRoutePattern('whiteboard.board'),
    element: whiteboardToolElement,
  },
];

export const whiteboardGlobalRoutes: StaticRouteDefinition[] = [
  {
    chrome: getAppRouteChrome('whiteboard.shared'),
    path: getAppRoutePattern('whiteboard.shared'),
    element: whiteboardToolElement,
  },
];
