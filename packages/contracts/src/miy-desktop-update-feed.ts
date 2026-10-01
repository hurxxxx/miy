const miyDesktopUpdatePlatforms = ['win', 'mac', 'linux'] as const;
const miyDesktopSupportedUpdatePlatforms =
  miyDesktopUpdatePlatforms.join(', ');
const miyDesktopUpdateFeedPathPrefix = '/api/v1/miy-desktop/updates';
const miyDesktopFallbackInstallerUrlEnvName =
  'VITE_MIY_DESKTOP_INSTALLER_URL';

export type MIYDesktopUpdatePlatform =
  (typeof miyDesktopUpdatePlatforms)[number];

export type MIYDesktopUpdatePlatformContract = {
  installerUrlEnvName: string;
  stableInstallerFileName: string;
};

const miyDesktopUpdatePlatformContracts = {
  win: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_WIN',
    stableInstallerFileName: 'MIY-Desktop-Setup-latest.exe',
  },
  mac: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_MAC',
    stableInstallerFileName: 'MIY-Desktop-latest.dmg',
  },
  linux: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_LINUX',
    stableInstallerFileName: 'MIY-Desktop-latest.deb',
  },
} as const satisfies Record<
  MIYDesktopUpdatePlatform,
  MIYDesktopUpdatePlatformContract
>;

const miyDesktopUpdatePlatformSet = new Set<string>(
  miyDesktopUpdatePlatforms,
);

export function isMIYDesktopUpdatePlatform(
  platform: unknown,
): platform is MIYDesktopUpdatePlatform {
  return (
    typeof platform === 'string' && miyDesktopUpdatePlatformSet.has(platform)
  );
}

export function normalizeMIYDesktopUpdatePlatform(
  platform: unknown,
): MIYDesktopUpdatePlatform {
  const normalized = String(platform ?? '').trim();
  if (!normalized) {
    throw new Error(
      `miy desktop update platform is required. Supported platforms: ${miyDesktopSupportedUpdatePlatforms}.`,
    );
  }
  if (isMIYDesktopUpdatePlatform(normalized)) {
    return normalized;
  }
  throw new Error(
    `Unsupported miy desktop update platform: ${normalized}. Supported platforms: ${miyDesktopSupportedUpdatePlatforms}.`,
  );
}

function miyDesktopInstallerUrlEnvName(
  platform: MIYDesktopUpdatePlatform,
): string {
  return miyDesktopUpdatePlatformContracts[
    normalizeMIYDesktopUpdatePlatform(platform)
  ].installerUrlEnvName;
}

function miyDesktopStableInstallerFileName(
  platform: MIYDesktopUpdatePlatform,
): string {
  return miyDesktopUpdatePlatformContracts[
    normalizeMIYDesktopUpdatePlatform(platform)
  ].stableInstallerFileName;
}

function miyDesktopUpdateFeedInstallerUrl(
  platform: MIYDesktopUpdatePlatform,
): string {
  const normalizedPlatform = normalizeMIYDesktopUpdatePlatform(platform);
  return [
    miyDesktopUpdateFeedPathPrefix,
    normalizedPlatform,
    miyDesktopStableInstallerFileName(normalizedPlatform),
  ].join('/');
}

export const MIYDesktopUpdateFeedContract = {
  platforms: miyDesktopUpdatePlatforms,
  feedPathPrefix: miyDesktopUpdateFeedPathPrefix,
  fallbackInstallerUrlEnvName: miyDesktopFallbackInstallerUrlEnvName,
  platformContracts: miyDesktopUpdatePlatformContracts,
  normalizePlatform: normalizeMIYDesktopUpdatePlatform,
  installerUrlEnvName: miyDesktopInstallerUrlEnvName,
  stableInstallerFileName: miyDesktopStableInstallerFileName,
  installerUrl: miyDesktopUpdateFeedInstallerUrl,
} as const;

export const MIY_DESKTOP_UPDATE_PLATFORMS =
  MIYDesktopUpdateFeedContract.platforms;

export const MIY_DESKTOP_UPDATE_FEED_PATH_PREFIX =
  MIYDesktopUpdateFeedContract.feedPathPrefix;

export const MIY_DESKTOP_INSTALLER_URL_ENV_NAMES: Record<
  MIYDesktopUpdatePlatform,
  string
> = {
  win: MIYDesktopUpdateFeedContract.installerUrlEnvName('win'),
  mac: MIYDesktopUpdateFeedContract.installerUrlEnvName('mac'),
  linux: MIYDesktopUpdateFeedContract.installerUrlEnvName('linux'),
};

export const MIY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME =
  MIYDesktopUpdateFeedContract.fallbackInstallerUrlEnvName;

export const MIY_DESKTOP_STABLE_INSTALLER_FILE_NAMES: Record<
  MIYDesktopUpdatePlatform,
  string
> = {
  win: MIYDesktopUpdateFeedContract.stableInstallerFileName('win'),
  mac: MIYDesktopUpdateFeedContract.stableInstallerFileName('mac'),
  linux: MIYDesktopUpdateFeedContract.stableInstallerFileName('linux'),
};

export function miyDesktopInstallerUrl(
  platform: MIYDesktopUpdatePlatform,
): string {
  return MIYDesktopUpdateFeedContract.installerUrl(platform);
}
