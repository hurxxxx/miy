import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const BentoView = lazy(() =>
  import('./views/BentoView').then((module) => ({
    default: module.BentoView,
  })),
);

export const bentoAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'bento',
    chrome: getAppRouteChrome('bento.root'),
    path: getAppRoutePattern('bento.root'),
    element: lazyRoute(createElement(BentoView)),
  },
  {
    appId: 'bento',
    chrome: getAppRouteChrome('bento.presentation'),
    path: getAppRoutePattern('bento.presentation'),
    element: lazyRoute(createElement(BentoView)),
  },
];
