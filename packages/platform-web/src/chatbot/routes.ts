import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { createElement, lazy } from 'react';

import { lazyRoute } from '../routing/index';
import type { AppRouteDefinition } from '@miy/core-web/navigation-types';

const ChatbotView = lazy(() =>
  import('./views/ChatbotView').then((module) => ({
    default: module.ChatbotView,
  })),
);

export const chatbotAppRoutes: AppRouteDefinition[] = [
  {
    appId: 'chatbot',
    chrome: getAppRouteChrome('chatbot.root'),
    path: getAppRoutePattern('chatbot.root'),
    element: lazyRoute(
      createElement(ChatbotView, {
        experience: { conversationListPlacement: 'shell' },
      }),
    ),
  },
];
