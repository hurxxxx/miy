import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { Activity, Calendar } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const plannerManifest: AppModuleManifest = {
  appBarItem: { id: 'planner', title: 'planner', icon: Calendar },
  contract: {
    owner: 'planner-platform',
    permissions: [],
    apiDomain: 'planner',
    aiCapabilities: [
      'planner.list_events',
      'planner.create_event',
      'planner.update_event',
      'planner.delete_event',
    ],
    writeAuditActions: [
      'planner.create_event',
      'planner.update_event',
      'planner.delete_event',
    ],
    appLocalTests: [
      'packages/official-suite-web/src/planner/api/planner-api.spec.ts',
      'packages/official-suite-web/src/planner/views/PlannerEventModal.spec.tsx',
      'packages/official-suite-web/src/planner/views/planner-event-modal-model.spec.ts',
      'packages/official-suite-web/src/planner/sidebar.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-calendar-schedule-policy.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-calendar-view-model.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-timeline-model.spec.ts',
      'packages/official-suite-web/src/planner/views/schedule-popover-model.spec.ts',
      'packages/official-suite-web/src/planner/views/WorldClocks.spec.tsx',
      'packages/official-suite-web/src/planner/views/floating-today-planner-model.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-calendar-controller.spec.ts',
      'packages/official-suite-web/src/planner/views/PlannerView.mutation.spec.tsx',
      'packages/official-suite-web/src/planner/views/planner-calendar-session.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-calendar-event-projection.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-event-choice-popover-model.spec.ts',
      'packages/official-suite-web/src/planner/views/planner-calendar-schedule-workflow.spec.ts',
      'packages/official-suite-web/src/calendar/calendar-events-session.spec.ts',
      'packages/official-suite-web/src/calendar/use-calendar-events.spec.tsx',
      'packages/official-suite-web/src/calendar/unified-calendar-adapter.spec.ts',
      'packages/platform-web/src/time/korean-holidays.spec.ts',
      'apps/web/src/app-modules/planner/planner-source-compatibility.spec.tsx',
      'apps/web/src/app-modules/planner/ownership.spec.tsx',
      'apps/web/src/app/shell/official-module-ownership.spec.tsx',
      'apps/api/tests/test_planner_events.py',
      'apps/api/tests/test_calendar_events.py',
    ],
  },
  defaultActiveNavItemId: 'planner-calendar',
  navItems: [
    {
      id: 'planner-calendar',
      title: 'planner-calendar',
      icon: Calendar,
      category: 'Schedule',
      appId: 'planner',
    },
    {
      id: 'planner-timeline',
      title: 'planner-timeline',
      icon: Activity,
      category: 'Schedule',
      appId: 'planner',
      pathSuffix: '?view=timeline',
    },
  ],
  appRoutePaths: [],
  globalRoutePaths: [getAppRoutePattern('planner.root')],
};
