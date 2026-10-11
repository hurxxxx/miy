import { OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';
import { pmsManifest } from './manifests/pms';
import { docsManifest } from './manifests/docs';
import { filesManifest } from './manifests/files';
import { mailManifest } from './manifests/mail';
import { communityManifest } from './manifests/community';
import { whiteboardManifest } from './manifests/whiteboard';
import { diagramsManifest } from './manifests/diagrams';
import { bentoManifest } from './manifests/bento';
import { plannerManifest } from './manifests/planner';
import { meetingManifest } from './manifests/meeting';
import { videoChatManifest } from './manifests/video-chat';
import { recordingManifest } from './manifests/recording';

export { pmsManifest } from './manifests/pms';
export { docsManifest } from './manifests/docs';
export { filesManifest } from './manifests/files';
export { mailManifest } from './manifests/mail';
export { communityManifest } from './manifests/community';
export { whiteboardManifest } from './manifests/whiteboard';
export { diagramsManifest } from './manifests/diagrams';
export { bentoManifest } from './manifests/bento';
export { plannerManifest } from './manifests/planner';
export { meetingManifest } from './manifests/meeting';
export { videoChatManifest } from './manifests/video-chat';
export { recordingManifest } from './manifests/recording';
export {
  OFFICIAL_HELP_GUIDES,
  getPmsHelpGuideSrc,
  pmsHelpGuideRegistration,
} from './help-guides';

const manifests = {
  pms: pmsManifest,
  docs: docsManifest,
  files: filesManifest,
  mail: mailManifest,
  community: communityManifest,
  whiteboard: whiteboardManifest,
  diagrams: diagramsManifest,
  bento: bentoManifest,
  planner: plannerManifest,
  meeting: meetingManifest,
  'video-chat': videoChatManifest,
  recording: recordingManifest,
} as const;

/** Membership and order come from the shared app contract; this library owns UI metadata. */
export const OFFICIAL_APP_MANIFESTS = OFFICIAL_APP_IDS.map(
  (id) => manifests[id],
);
