const mtyDesktopUpdatePlatforms = ['win', 'mac', 'linux'] as const;
const mtyDesktopSupportedUpdatePlatforms =
  mtyDesktopUpdatePlatforms.join(', ');
const mtyDesktopUpdateFeedPathPrefix = '/api/v1/mty-desktop/updates';
const mtyDesktopFallbackInstallerUrlEnvName =
  'VITE_MTY_DESKTOP_INSTALLER_URL';

export type MTYDesktopUpdatePlatform =
  (typeof mtyDesktopUpdatePlatforms)[number];

export type MTYDesktopUpdatePlatformContract = {
  installerUrlEnvName: string;
  stableInstallerFileName: string;
};

const mtyDesktopUpdatePlatformContracts = {
  win: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_WIN',
    stableInstallerFileName: 'MTY-Desktop-Setup-latest.exe',
  },
  mac: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_MAC',
    stableInstallerFileName: 'MTY-Desktop-latest.dmg',
  },
  linux: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_LINUX',
    stableInstallerFileName: 'MTY-Desktop-latest.deb',
  },
} as const satisfies Record<
  MTYDesktopUpdatePlatform,
  MTYDesktopUpdatePlatformContract
>;

const mtyDesktopUpdatePlatformSet = new Set<string>(
  mtyDesktopUpdatePlatforms,
);

export function isMTYDesktopUpdatePlatform(
  platform: unknown,
): platform is MTYDesktopUpdatePlatform {
  return (
    typeof platform === 'string' && mtyDesktopUpdatePlatformSet.has(platform)
  );
}

export function normalizeMTYDesktopUpdatePlatform(
  platform: unknown,
): MTYDesktopUpdatePlatform {
  const normalized = String(platform ?? '').trim();
  if (!normalized) {
    throw new Error(
      `MTY desktop update platform is required. Supported platforms: ${mtyDesktopSupportedUpdatePlatforms}.`,
    );
  }
  if (isMTYDesktopUpdatePlatform(normalized)) {
    return normalized;
  }
  throw new Error(
    `Unsupported MTY desktop update platform: ${normalized}. Supported platforms: ${mtyDesktopSupportedUpdatePlatforms}.`,
  );
}

function mtyDesktopInstallerUrlEnvName(
  platform: MTYDesktopUpdatePlatform,
): string {
  return mtyDesktopUpdatePlatformContracts[
    normalizeMTYDesktopUpdatePlatform(platform)
  ].installerUrlEnvName;
}

function mtyDesktopStableInstallerFileName(
  platform: MTYDesktopUpdatePlatform,
): string {
  return mtyDesktopUpdatePlatformContracts[
    normalizeMTYDesktopUpdatePlatform(platform)
  ].stableInstallerFileName;
}

function mtyDesktopUpdateFeedInstallerUrl(
  platform: MTYDesktopUpdatePlatform,
): string {
  const normalizedPlatform = normalizeMTYDesktopUpdatePlatform(platform);
  return [
    mtyDesktopUpdateFeedPathPrefix,
    normalizedPlatform,
    mtyDesktopStableInstallerFileName(normalizedPlatform),
  ].join('/');
}

export const MTYDesktopUpdateFeedContract = {
  platforms: mtyDesktopUpdatePlatforms,
  feedPathPrefix: mtyDesktopUpdateFeedPathPrefix,
  fallbackInstallerUrlEnvName: mtyDesktopFallbackInstallerUrlEnvName,
  platformContracts: mtyDesktopUpdatePlatformContracts,
  normalizePlatform: normalizeMTYDesktopUpdatePlatform,
  installerUrlEnvName: mtyDesktopInstallerUrlEnvName,
  stableInstallerFileName: mtyDesktopStableInstallerFileName,
  installerUrl: mtyDesktopUpdateFeedInstallerUrl,
} as const;

export const MTY_DESKTOP_UPDATE_PLATFORMS =
  MTYDesktopUpdateFeedContract.platforms;

export const MTY_DESKTOP_UPDATE_FEED_PATH_PREFIX =
  MTYDesktopUpdateFeedContract.feedPathPrefix;

export const MTY_DESKTOP_INSTALLER_URL_ENV_NAMES: Record<
  MTYDesktopUpdatePlatform,
  string
> = {
  win: MTYDesktopUpdateFeedContract.installerUrlEnvName('win'),
  mac: MTYDesktopUpdateFeedContract.installerUrlEnvName('mac'),
  linux: MTYDesktopUpdateFeedContract.installerUrlEnvName('linux'),
};

export const MTY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME =
  MTYDesktopUpdateFeedContract.fallbackInstallerUrlEnvName;

export const MTY_DESKTOP_STABLE_INSTALLER_FILE_NAMES: Record<
  MTYDesktopUpdatePlatform,
  string
> = {
  win: MTYDesktopUpdateFeedContract.stableInstallerFileName('win'),
  mac: MTYDesktopUpdateFeedContract.stableInstallerFileName('mac'),
  linux: MTYDesktopUpdateFeedContract.stableInstallerFileName('linux'),
};

export function mtyDesktopInstallerUrl(
  platform: MTYDesktopUpdatePlatform,
): string {
  return MTYDesktopUpdateFeedContract.installerUrl(platform);
}
