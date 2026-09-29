import { DesktopInstallerPanel } from './desktop-installer-panel';
import type { SettingsTranslator } from './settings-page-model';
import { SettingsSectionHeader } from './SettingsSectionHeader';

export function MTYDesktopSettingsSection({
  t,
}: {
  t: SettingsTranslator;
}) {
  return (
    <div>
      <SettingsSectionHeader
        title={t('auth:settings.mtyDesktop')}
        description={t('auth:settings.mtyDesktopSettingsDescription')}
      />

      <div className="border-t border-app-border">
        <DesktopInstallerPanel />
      </div>
    </div>
  );
}
