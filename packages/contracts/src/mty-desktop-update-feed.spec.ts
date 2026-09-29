import { describe, expect, it } from 'vitest';

import {
  MTYDesktopUpdateFeedContract,
  MTY_DESKTOP_INSTALLER_URL_ENV_NAMES,
  MTY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME,
  MTY_DESKTOP_STABLE_INSTALLER_FILE_NAMES,
  MTY_DESKTOP_UPDATE_FEED_PATH_PREFIX,
  MTY_DESKTOP_UPDATE_PLATFORMS,
  mtyDesktopInstallerUrl,
  isMTYDesktopUpdatePlatform,
  normalizeMTYDesktopUpdatePlatform,
  type MTYDesktopUpdatePlatform,
} from './mty-desktop-update-feed';

const expectedPlatformContracts = {
  win: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_WIN',
    stableInstallerFileName: 'MTY-Desktop-Setup-latest.exe',
    installerUrl:
      '/api/v1/mty-desktop/updates/win/MTY-Desktop-Setup-latest.exe',
  },
  mac: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_MAC',
    stableInstallerFileName: 'MTY-Desktop-latest.dmg',
    installerUrl: '/api/v1/mty-desktop/updates/mac/MTY-Desktop-latest.dmg',
  },
  linux: {
    installerUrlEnvName: 'VITE_MTY_DESKTOP_INSTALLER_URL_LINUX',
    stableInstallerFileName: 'MTY-Desktop-latest.deb',
    installerUrl:
      '/api/v1/mty-desktop/updates/linux/MTY-Desktop-latest.deb',
  },
} as const satisfies Record<
  MTYDesktopUpdatePlatform,
  {
    installerUrlEnvName: string;
    stableInstallerFileName: string;
    installerUrl: string;
  }
>;

describe('MTY desktop update feed contract', () => {
  it('keeps the existing exported constants on the contract values', () => {
    expect(MTY_DESKTOP_UPDATE_PLATFORMS).toEqual(['win', 'mac', 'linux']);
    expect(MTY_DESKTOP_UPDATE_PLATFORMS).toBe(
      MTYDesktopUpdateFeedContract.platforms,
    );
    expect(MTY_DESKTOP_UPDATE_FEED_PATH_PREFIX).toBe(
      '/api/v1/mty-desktop/updates',
    );
    expect(MTY_DESKTOP_UPDATE_FEED_PATH_PREFIX).toBe(
      MTYDesktopUpdateFeedContract.feedPathPrefix,
    );
    expect(MTY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME).toBe(
      'VITE_MTY_DESKTOP_INSTALLER_URL',
    );
    expect(MTY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME).toBe(
      MTYDesktopUpdateFeedContract.fallbackInstallerUrlEnvName,
    );
  });

  it('exports complete env and stable installer maps for each platform', () => {
    const platforms = [...MTY_DESKTOP_UPDATE_PLATFORMS];

    expect(Object.keys(MTY_DESKTOP_INSTALLER_URL_ENV_NAMES).sort()).toEqual(
      [...platforms].sort(),
    );
    expect(
      Object.keys(MTY_DESKTOP_STABLE_INSTALLER_FILE_NAMES).sort(),
    ).toEqual([...platforms].sort());

    expect(MTY_DESKTOP_INSTALLER_URL_ENV_NAMES).toEqual({
      win: 'VITE_MTY_DESKTOP_INSTALLER_URL_WIN',
      mac: 'VITE_MTY_DESKTOP_INSTALLER_URL_MAC',
      linux: 'VITE_MTY_DESKTOP_INSTALLER_URL_LINUX',
    });
    expect(MTY_DESKTOP_STABLE_INSTALLER_FILE_NAMES).toEqual({
      win: 'MTY-Desktop-Setup-latest.exe',
      mac: 'MTY-Desktop-latest.dmg',
      linux: 'MTY-Desktop-latest.deb',
    });

    for (const platform of platforms) {
      expect(MTY_DESKTOP_INSTALLER_URL_ENV_NAMES[platform]).toBe(
        expectedPlatformContracts[platform].installerUrlEnvName,
      );
      expect(MTY_DESKTOP_STABLE_INSTALLER_FILE_NAMES[platform]).toBe(
        expectedPlatformContracts[platform].stableInstallerFileName,
      );
      expect(MTYDesktopUpdateFeedContract.platformContracts[platform]).toEqual(
        {
          installerUrlEnvName:
            expectedPlatformContracts[platform].installerUrlEnvName,
          stableInstallerFileName:
            expectedPlatformContracts[platform].stableInstallerFileName,
        },
      );
    }
  });

  it('constructs each platform installer URL through the contract', () => {
    for (const platform of MTY_DESKTOP_UPDATE_PLATFORMS) {
      expect(mtyDesktopInstallerUrl(platform)).toBe(
        expectedPlatformContracts[platform].installerUrl,
      );
      expect(MTYDesktopUpdateFeedContract.installerUrl(platform)).toBe(
        expectedPlatformContracts[platform].installerUrl,
      );
    }
  });

  it('normalizes known platforms and rejects unsupported platform input', () => {
    expect(normalizeMTYDesktopUpdatePlatform(' mac ')).toBe('mac');
    expect(isMTYDesktopUpdatePlatform('win')).toBe(true);
    expect(isMTYDesktopUpdatePlatform('darwin')).toBe(false);

    expect(() => normalizeMTYDesktopUpdatePlatform('')).toThrow(
      'MTY desktop update platform is required. Supported platforms: win, mac, linux.',
    );

    const unsupportedPlatform = 'darwin' as MTYDesktopUpdatePlatform;
    expect(() =>
      normalizeMTYDesktopUpdatePlatform(unsupportedPlatform),
    ).toThrow(
      'Unsupported MTY desktop update platform: darwin. Supported platforms: win, mac, linux.',
    );
    expect(() => mtyDesktopInstallerUrl(unsupportedPlatform)).toThrow(
      'Unsupported MTY desktop update platform: darwin. Supported platforms: win, mac, linux.',
    );
  });
});
