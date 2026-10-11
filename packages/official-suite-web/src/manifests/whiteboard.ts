import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { History, PencilRuler, Star, Trash2, User } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const whiteboardManifest: AppModuleManifest = {
  appBarItem: { id: 'whiteboard', title: 'whiteboard', icon: PencilRuler },
  contract: {
    owner: 'whiteboard-platform',
    permissions: [],
    apiDomain: 'whiteboard',
    aiCapabilities: [],
    writeAuditActions: [],
    appLocalTests: [
      'apps/api/tests/test_whiteboard_hub.py',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-picker-model.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-context-slot-panel-model.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-collab-runtime-model.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-preview-loader.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/useWhiteboardScenePersistence.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-hub-model.spec.ts',
      'apps/web/src/app-modules/whiteboard/views/WhiteboardContextSlotPanel.spec.tsx',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-editor-session.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-collab-runtime.spec.ts',
      'apps/web/src/app-modules/whiteboard/views/WhiteboardView.spec.tsx',
      'packages/official-suite-web/src/whiteboard/views/WhiteboardGroupSharing.spec.tsx',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-collab-scene.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/WhiteboardAccessBoundary.spec.tsx',
      'packages/official-suite-web/src/whiteboard/views/whiteboard-share-model.spec.ts',
      'packages/official-suite-web/src/whiteboard/views/WhiteboardEditorSurface.spec.tsx',
      'packages/official-suite-web/src/whiteboard/api/whiteboard-api.spec.ts',
      'apps/web/src/app/shell/whiteboard-ownership.spec.tsx',
      'apps/web/src/app/shell/official-module-ownership.spec.tsx',
    ],
  },
  defaultActiveNavItemId: 'whiteboard-all',
  navItems: [
    {
      id: 'whiteboard-all',
      title: 'whiteboard-all',
      icon: PencilRuler,
      category: 'Library',
      appId: 'whiteboard',
    },
    {
      id: 'whiteboard-my',
      title: 'whiteboard-my',
      icon: User,
      category: 'Library',
      appId: 'whiteboard',
      pathSuffix: '?view=mine',
    },
    {
      id: 'whiteboard-recent',
      title: 'whiteboard-recent',
      icon: History,
      category: 'Library',
      appId: 'whiteboard',
      pathSuffix: '?view=recent',
    },
    {
      id: 'whiteboard-favorites',
      title: 'whiteboard-favorites',
      icon: Star,
      category: 'Library',
      appId: 'whiteboard',
      pathSuffix: '?view=favorites',
    },
    {
      id: 'whiteboard-archived',
      title: 'whiteboard-archived',
      icon: Trash2,
      category: 'Library',
      appId: 'whiteboard',
      pathSuffix: '?view=archived',
    },
  ],
  appRoutePaths: [
    getAppRoutePattern('whiteboard.root'),
    getAppRoutePattern('whiteboard.board'),
  ],
  globalRoutePaths: [getAppRoutePattern('whiteboard.shared')],
};
