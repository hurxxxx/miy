import { DesktopInstallerPanel } from './desktop-installer-panel';
import type { SettingsTranslator } from './settings-page-model';
import { SettingsSectionHeader } from './SettingsSectionHeader';

export function MIYDesktopSettingsSection({
  t,
}: {
  t: SettingsTranslator;
}) {
  return (
    <div>
      <SettingsSectionHeader
        title={t('auth:settings.miyDesktop')}
        description={t('auth:settings.miyDesktopSettingsDescription')}
      />

      <div className="border-t border-app-border">
        <DesktopInstallerPanel />
      </div>
    </div>
  );
}
