import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { MessageSquare } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const chatbotManifest: AppModuleManifest = {
  appBarItem: { id: 'chatbot', title: 'chatbot', icon: MessageSquare },
  contract: {
    owner: 'ai-platform',
    permissions: [],
    apiDomain: 'ai',
    aiCapabilities: [],
    writeAuditActions: [],
    appLocalTests: [
      'packages/platform-web/src/chatbot/api/sse-parser.spec.ts',
      'packages/platform-web/src/chatbot/api/chat-stream-state.spec.ts',
      'packages/platform-web/src/chatbot/api/useChatStream.spec.tsx',
      'apps/api/tests/test_ai.py',
    ],
  },
  defaultActiveNavItemId: '',
  navItems: [],
  appRoutePaths: [getAppRoutePattern('chatbot.root')],
};
