import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { Archive, Presentation, User } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const bentoManifest: AppModuleManifest = {
  appBarItem: { id: 'bento', title: 'bento', icon: Presentation },
  contract: {
    owner: 'collaboration-platform',
    permissions: [],
    apiDomain: 'bento',
    aiCapabilities: [],
    writeAuditActions: [],
    appLocalTests: [
      'apps/web/src/app/shell/official-module-ownership.spec.tsx',
      'apps/api/tests/test_bento_documents.py',
      'packages/official-suite-web/src/bento/bento-route-paths.spec.ts',
      'packages/official-suite-web/src/bento/views/bento-embed-protocol.spec.ts',
      'packages/official-suite-web/src/bento/views/bento-bridge.spec.ts',
      'packages/official-suite-web/src/bento/views/BentoView.spec.tsx',
    ],
  },
  defaultActiveNavItemId: 'bento-all',
  navItems: [
    {
      id: 'bento-all',
      title: 'bento-all',
      icon: Presentation,
      category: 'Library',
      appId: 'bento',
    },
    {
      id: 'bento-mine',
      title: 'bento-mine',
      icon: User,
      category: 'Library',
      appId: 'bento',
      pathSuffix: '?view=mine',
    },
    {
      id: 'bento-archived',
      title: 'bento-archived',
      icon: Archive,
      category: 'Library',
      appId: 'bento',
      pathSuffix: '?view=archived',
    },
  ],
  appRoutePaths: [
    getAppRoutePattern('bento.root'),
    getAppRoutePattern('bento.presentation'),
  ],
};
