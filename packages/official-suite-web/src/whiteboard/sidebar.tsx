import { PencilRuler } from 'lucide-react';

import type { AppSidebarConfig } from '@miy/platform-web/routing';

export const whiteboardSidebarConfig: AppSidebarConfig = {
  createActions: () => [
    {
      id: 'whiteboard-create',
      label: 'whiteboard-create',
      labelKey: 'sidebarActions.whiteboard-create',
      icon: PencilRuler,
      run: () => {
        window.dispatchEvent(new CustomEvent('whiteboard:create'));
      },
    },
  ],
};
