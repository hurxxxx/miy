import { BookOpen } from 'lucide-react';

import type { HelpGuide } from '@miy/core-web/help-guide';
import { pmsManifest } from './manifests/pms';

const appId = pmsManifest.appBarItem.id;
const guideSrc = `/help/${appId}/user-guide.html`;

export function getPmsHelpGuideSrc(locale: string | undefined): string {
  return locale?.toLowerCase().startsWith('en')
    ? `${guideSrc}#english`
    : guideSrc;
}

export const pmsHelpGuideRegistration = {
  descriptionKey: 'shell:helpCenter.pmsGuideDescription',
  getSrc: getPmsHelpGuideSrc,
  icon: BookOpen,
  key: appId,
  routePath: `/help/${appId}`,
  src: guideSrc,
  titleKey: 'shell:helpCenter.pmsGuideTitle',
} as const satisfies HelpGuide;

/** Guides selected by the official business suite for both shell compositions. */
export const OFFICIAL_HELP_GUIDES: readonly HelpGuide[] = [
  pmsHelpGuideRegistration,
];
