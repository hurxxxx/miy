import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '@miy/platform-web/routing';
import type { StaticRouteDefinition } from '@miy/core-web/navigation-types';

const MailView = lazy(() =>
  import('./views/MailView').then((module) => ({
    default: module.MailView,
  })),
);

export const mailGlobalRoutes: StaticRouteDefinition[] = [
  {
    chrome: getAppRouteChrome('mail.root'),
    path: getAppRoutePattern('mail.root'),
    element: lazyRoute(createElement(MailView)),
  },
];
