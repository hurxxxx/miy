import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { StaticRouteDefinition } from '@miy/core-web/navigation-types';

const CommunityView = lazy(() =>
  import('./views/CommunityView').then((module) => ({
    default: module.CommunityView,
  })),
);

export const communityGlobalRoutes: StaticRouteDefinition[] = [
  {
    chrome: getAppRouteChrome('community.root'),
    path: getAppRoutePattern('community.root'),
    element: lazyRoute(createElement(CommunityView)),
  },
  {
    chrome: getAppRouteChrome('community.post'),
    path: getAppRoutePattern('community.post'),
    element: lazyRoute(createElement(CommunityView)),
  },
];
