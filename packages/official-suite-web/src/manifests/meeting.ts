import { getAppRoutePattern } from '@miy/contracts/app-routes';
import { Calendar, User, Users, Video } from 'lucide-react';

import type { AppModuleManifest } from '@miy/core-web/navigation-types';

export const meetingManifest: AppModuleManifest = {
  appBarItem: { id: 'meeting', title: 'meeting', icon: Users },
  contract: {
    owner: 'meeting-platform',
    permissions: [],
    apiDomain: 'meeting',
    aiCapabilities: [
      'meeting.list_meetings',
      'meeting.get_meeting',
      'meeting.find_availability',
      'meeting.extract_actions',
      'meeting.extract_decisions',
      'meeting.draft_followup_schedule',
      'meeting.create_meeting',
    ],
    writeAuditActions: ['ai_meeting_insight_created', 'meeting.create_meeting'],
    appLocalTests: [
      'packages/official-suite-web/src/meeting/api/meeting-api.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingPickerModal.spec.tsx',
      'packages/official-suite-web/src/meeting/views/meeting-picker-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-availability-modal-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meetingAvailability.spec.tsx',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-detail-layout-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-detail-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-form-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-form-submission.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-form-workflow.spec.tsx',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-insight-chat-handoff.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/meeting-list-view-model.spec.ts',
      'packages/official-suite-web/src/meeting/views/MeetingView/TaskPickerModal.spec.tsx',
      'packages/official-suite-web/src/meeting/views/MeetingView/useMeetingUserSearch.spec.ts',
      'apps/web/src/app-modules/meeting/api/meeting-permissions.spec.ts',
      'apps/web/src/app-modules/meeting/ownership.spec.tsx',
      'apps/web/src/app/shell/official-module-ownership.spec.tsx',
      'apps/web/src/app-modules/chatbot/api/shared-ai-transport.spec.ts',
      'apps/web/src/platform/apps/shared-app-admission.spec.tsx',
      'apps/api/tests/test_meeting.py',
    ],
  },
  defaultActiveNavItemId: 'meeting-upcoming',
  navItems: [
    {
      id: 'meeting-upcoming',
      title: 'meeting-upcoming',
      icon: Calendar,
      category: 'Meetings',
      appId: 'meeting',
    },
    {
      id: 'meeting-mine',
      title: 'meeting-mine',
      icon: User,
      category: 'Meetings',
      appId: 'meeting',
      pathSuffix: '?scope=mine',
    },
    {
      id: 'meeting-recordings',
      title: 'meeting-recordings',
      icon: Video,
      category: 'Meetings',
      appId: 'meeting',
      pathSuffix: '?tab=recordings',
    },
  ],
  appRoutePaths: [
    getAppRoutePattern('meeting.root'),
    getAppRoutePattern('meeting.detail'),
  ],
};
