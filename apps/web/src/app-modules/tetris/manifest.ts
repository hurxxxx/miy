import { getAppRoutePattern } from '@open-work-hub/contracts/app-routes';
import { Boxes } from 'lucide-react';
import type { AppModuleManifest } from '@/src/app/shell/navigation-types';
export const tetrisManifest: AppModuleManifest = {
  appBarItem: { id: 'tetris', title: 'tetris', icon: Boxes },
  contract: {
    owner: 'collaboration-platform',
    permissions: [],
    apiDomain: 'tetris',
    aiCapabilities: [],
    writeAuditActions: [],
    appLocalTests: [
      'apps/web/src/app-modules/tetris/engine.spec.ts',
      'apps/web/src/app-modules/tetris/ai-candidates.spec.ts',
      'apps/web/src/app-modules/tetris/ai-api.spec.ts',
      'apps/web/src/app-modules/tetris/use-tetris.spec.tsx',
      'apps/web/src/app-modules/tetris/TetrisView.spec.tsx',
      'apps/api/tests/test_tetris_app.py',
      'apps/api/tests/test_tetris_decision.py',
    ],
  },
  defaultActiveNavItemId: 'tetris',
  navItems: [],
  appRoutePaths: [],
  globalRoutePaths: [getAppRoutePattern('tetris.root')],
};
