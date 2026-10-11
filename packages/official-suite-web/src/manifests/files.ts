import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { Bot, FolderOpen, Search } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const filesManifest: AppModuleManifest = {
  appBarItem: { id: 'files', title: 'files', icon: FolderOpen },
  contract: {
    owner: 'files-platform',
    permissions: [],
    apiDomain: 'files',
    aiCapabilities: ['files.grounded_chat', 'files.rag_query_rewrite'],
    writeAuditActions: [],
    appLocalTests: [
      'packages/official-suite-web/src/files/api/files-api.spec.ts',
      'apps/web/src/app-modules/files/manifest.spec.ts',
      'apps/web/src/app-modules/files/files-source-compatibility.spec.tsx',
      'apps/web/src/app-modules/files/ownership.spec.tsx',
      'packages/official-suite-web/src/files/routes.spec.tsx',
      'packages/official-suite-web/src/files/sidebar.spec.tsx',
      'packages/official-suite-web/src/files/views/FilesChatView.spec.tsx',
      'packages/official-suite-web/src/files/views/FilesRagSourcesArtifact.spec.tsx',
      'packages/official-suite-web/src/files/views/FileManagerWorkflow.spec.ts',
      'packages/official-suite-web/src/files/views/FileSearchView.spec.tsx',
      'packages/official-suite-web/src/files/views/file-search-view-model.spec.ts',
      'packages/official-suite-web/src/files/views/useFileSearchController.spec.ts',
      'apps/api/tests/test_file_manager.py',
      'apps/api/tests/test_files_search.py',
    ],
  },
  defaultActiveNavItemId: 'files-all',
  navItems: [
    {
      id: 'files-all',
      title: 'files-all',
      icon: FolderOpen,
      category: 'Drive',
      appId: 'files',
    },
    {
      id: 'files-search',
      title: 'files-search',
      icon: Search,
      category: 'Drive',
      appId: 'files',
      pathSuffix: '?view=search',
    },
    {
      id: 'files-chat',
      title: 'files-chat',
      icon: Bot,
      category: 'Drive',
      appId: 'files',
      pathSuffix: '/chat',
    },
  ],
  appRoutePaths: [
    getAppRoutePattern('files.root'),
    getAppRoutePattern('files.chat'),
  ],
};
