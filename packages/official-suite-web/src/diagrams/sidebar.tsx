import { Workflow } from 'lucide-react';

import type { AppSidebarConfig } from '@miy/platform-web/routing';

export const diagramsSidebarConfig: AppSidebarConfig = {
  createActions: () => [
    {
      id: 'diagrams-create',
      label: 'diagrams-create',
      labelKey: 'sidebarActions.diagrams-create',
      icon: Workflow,
      run: () => {
        window.dispatchEvent(new CustomEvent('diagrams:create'));
      },
    },
  ],
};
