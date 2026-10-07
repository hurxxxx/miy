import type { LucideIcon } from 'lucide-react';

export type HelpGuide = {
  key: string;
  descriptionKey: string;
  getSrc?: (locale: string | undefined) => string;
  icon: LucideIcon;
  routePath: string;
  src: string;
  titleKey: string;
};
