import { OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';
import { pmsModule } from '@miy/official-suite-web/pms/module';
import { docsModule } from '@miy/official-suite-web/docs/module';
import { filesModule } from '@miy/official-suite-web/files/module';
import { mailModule } from '@miy/official-suite-web/mail/module';
import { communityModule } from '@miy/official-suite-web/community/module';
import { whiteboardModule } from '@miy/official-suite-web/whiteboard/module';
import { diagramsModule } from '@miy/official-suite-web/diagrams/module';
import { bentoModule } from '@miy/official-suite-web/bento/module';
import { plannerModule } from '@miy/official-suite-web/planner/module';
import { meetingModule } from '@miy/official-suite-web/meeting/module';
import { videoChatModule } from '@miy/official-suite-web/video-chat/module';
import { recordingModule } from '@miy/official-suite-web/recording/module';

// The suite owns all official UI module implementations.
// Source ownership does not activate their independent services or releases.
// The shared contract owns membership/order for both UI compositions.
const modules = {
  pms: pmsModule,
  docs: docsModule,
  files: filesModule,
  mail: mailModule,
  community: communityModule,
  whiteboard: whiteboardModule,
  diagrams: diagramsModule,
  bento: bentoModule,
  planner: plannerModule,
  meeting: meetingModule,
  'video-chat': videoChatModule,
  recording: recordingModule,
} as const;
export const OFFICIAL_APP_MODULES = OFFICIAL_APP_IDS.map((id) => modules[id]);
