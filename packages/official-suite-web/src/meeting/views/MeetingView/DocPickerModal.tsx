import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import {
  buildMeetingDocsHubPickerAdapter,
  DocsHubPickerModal,
  pickDocsHubSelectionItem,
  resolveDocsHubPickerExcludeDocIds,
  type DocsHubItem,
} from '../../../docs';
import { useAuth } from '@miy/platform-web/auth-context';
import { normalizeTimeZone } from '@miy/platform-web/time/time-utils';

interface DocPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPick: (doc: DocsHubItem) => Promise<void> | void;
  excludeDocIds?: string[];
}

export function DocPickerModal({
  isOpen,
  onClose,
  onPick,
  excludeDocIds,
}: DocPickerModalProps) {
  const { t, i18n } = useTranslation('apps');
  const { user } = useAuth();
  const timeZone = normalizeTimeZone(user?.time_zone);
  const adapter = useMemo(
    () =>
      buildMeetingDocsHubPickerAdapter({
        locale: i18n.language,
        t,
        timeZone,
      }),
    [i18n.language, t, timeZone],
  );

  return (
    <DocsHubPickerModal
      isOpen={isOpen}
      onClose={onClose}
      excludeDocIds={resolveDocsHubPickerExcludeDocIds(excludeDocIds)}
      adapter={adapter}
      onPick={pickDocsHubSelectionItem(onPick)}
    />
  );
}
