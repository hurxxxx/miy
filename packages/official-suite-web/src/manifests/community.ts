import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { MessagesSquare } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const communityManifest: AppModuleManifest = {
  appBarItem: { id: 'community', title: 'community', icon: MessagesSquare },
  contract: {
    owner: 'community-platform',
    permissions: [],
    apiDomain: 'community',
    aiCapabilities: [],
    writeAuditActions: [
      'community.channel.create',
      'community.channel.update',
      'community.channel.delete',
      'community.post.create',
      'community.post.update',
      'community.post.delete',
      'community.comment.create',
      'community.comment.update',
      'community.comment.delete',
    ],
    appLocalTests: [
      'packages/official-suite-web/src/community/api/community-api.spec.ts',
      'packages/official-suite-web/src/community/community-url.spec.ts',
      'packages/official-suite-web/src/community/manifest.spec.ts',
      'apps/web/src/app-modules/community/views/CommunityView.spec.tsx',
      'apps/web/src/app-modules/community/ownership.spec.tsx',
      'apps/web/src/app/shell/official-module-ownership.spec.tsx',
      'apps/api/tests/test_community.py',
    ],
  },
  defaultActiveNavItemId: '',
  navItems: [
    {
      id: 'community',
      title: 'community',
      icon: MessagesSquare,
      category: 'community',
      appId: 'community',
    },
  ],
  appRoutePaths: [],
  globalRoutePaths: [
    getAppRoutePattern('community.root'),
    getAppRoutePattern('community.post'),
  ],
};
