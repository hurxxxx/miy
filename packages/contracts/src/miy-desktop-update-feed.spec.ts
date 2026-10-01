import { describe, expect, it } from 'vitest';

import {
  MIYDesktopUpdateFeedContract,
  MIY_DESKTOP_INSTALLER_URL_ENV_NAMES,
  MIY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME,
  MIY_DESKTOP_STABLE_INSTALLER_FILE_NAMES,
  MIY_DESKTOP_UPDATE_FEED_PATH_PREFIX,
  MIY_DESKTOP_UPDATE_PLATFORMS,
  miyDesktopInstallerUrl,
  isMIYDesktopUpdatePlatform,
  normalizeMIYDesktopUpdatePlatform,
  type MIYDesktopUpdatePlatform,
} from './miy-desktop-update-feed';

const expectedPlatformContracts = {
  win: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_WIN',
    stableInstallerFileName: 'MIY-Desktop-Setup-latest.exe',
    installerUrl:
      '/api/v1/miy-desktop/updates/win/MIY-Desktop-Setup-latest.exe',
  },
  mac: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_MAC',
    stableInstallerFileName: 'MIY-Desktop-latest.dmg',
    installerUrl: '/api/v1/miy-desktop/updates/mac/MIY-Desktop-latest.dmg',
  },
  linux: {
    installerUrlEnvName: 'VITE_MIY_DESKTOP_INSTALLER_URL_LINUX',
    stableInstallerFileName: 'MIY-Desktop-latest.deb',
    installerUrl:
      '/api/v1/miy-desktop/updates/linux/MIY-Desktop-latest.deb',
  },
} as const satisfies Record<
  MIYDesktopUpdatePlatform,
  {
    installerUrlEnvName: string;
    stableInstallerFileName: string;
    installerUrl: string;
  }
>;

describe('miy desktop update feed contract', () => {
  it('keeps the existing exported constants on the contract values', () => {
    expect(MIY_DESKTOP_UPDATE_PLATFORMS).toEqual(['win', 'mac', 'linux']);
    expect(MIY_DESKTOP_UPDATE_PLATFORMS).toBe(
      MIYDesktopUpdateFeedContract.platforms,
    );
    expect(MIY_DESKTOP_UPDATE_FEED_PATH_PREFIX).toBe(
      '/api/v1/miy-desktop/updates',
    );
    expect(MIY_DESKTOP_UPDATE_FEED_PATH_PREFIX).toBe(
      MIYDesktopUpdateFeedContract.feedPathPrefix,
    );
    expect(MIY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME).toBe(
      'VITE_MIY_DESKTOP_INSTALLER_URL',
    );
    expect(MIY_DESKTOP_FALLBACK_INSTALLER_URL_ENV_NAME).toBe(
      MIYDesktopUpdateFeedContract.fallbackInstallerUrlEnvName,
    );
  });

  it('exports complete env and stable installer maps for each platform', () => {
    const platforms = [...MIY_DESKTOP_UPDATE_PLATFORMS];

    expect(Object.keys(MIY_DESKTOP_INSTALLER_URL_ENV_NAMES).sort()).toEqual(
      [...platforms].sort(),
    );
    expect(
      Object.keys(MIY_DESKTOP_STABLE_INSTALLER_FILE_NAMES).sort(),
    ).toEqual([...platforms].sort());

    expect(MIY_DESKTOP_INSTALLER_URL_ENV_NAMES).toEqual({
      win: 'VITE_MIY_DESKTOP_INSTALLER_URL_WIN',
      mac: 'VITE_MIY_DESKTOP_INSTALLER_URL_MAC',
      linux: 'VITE_MIY_DESKTOP_INSTALLER_URL_LINUX',
    });
    expect(MIY_DESKTOP_STABLE_INSTALLER_FILE_NAMES).toEqual({
      win: 'MIY-Desktop-Setup-latest.exe',
      mac: 'MIY-Desktop-latest.dmg',
      linux: 'MIY-Desktop-latest.deb',
    });

    for (const platform of platforms) {
      expect(MIY_DESKTOP_INSTALLER_URL_ENV_NAMES[platform]).toBe(
        expectedPlatformContracts[platform].installerUrlEnvName,
      );
      expect(MIY_DESKTOP_STABLE_INSTALLER_FILE_NAMES[platform]).toBe(
        expectedPlatformContracts[platform].stableInstallerFileName,
      );
      expect(MIYDesktopUpdateFeedContract.platformContracts[platform]).toEqual(
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
    for (const platform of MIY_DESKTOP_UPDATE_PLATFORMS) {
      expect(miyDesktopInstallerUrl(platform)).toBe(
        expectedPlatformContracts[platform].installerUrl,
      );
      expect(MIYDesktopUpdateFeedContract.installerUrl(platform)).toBe(
        expectedPlatformContracts[platform].installerUrl,
      );
    }
  });

  it('normalizes known platforms and rejects unsupported platform input', () => {
    expect(normalizeMIYDesktopUpdatePlatform(' mac ')).toBe('mac');
    expect(isMIYDesktopUpdatePlatform('win')).toBe(true);
    expect(isMIYDesktopUpdatePlatform('darwin')).toBe(false);

    expect(() => normalizeMIYDesktopUpdatePlatform('')).toThrow(
      'miy desktop update platform is required. Supported platforms: win, mac, linux.',
    );

    const unsupportedPlatform = 'darwin' as MIYDesktopUpdatePlatform;
    expect(() =>
      normalizeMIYDesktopUpdatePlatform(unsupportedPlatform),
    ).toThrow(
      'Unsupported miy desktop update platform: darwin. Supported platforms: win, mac, linux.',
    );
    expect(() => miyDesktopInstallerUrl(unsupportedPlatform)).toThrow(
      'Unsupported miy desktop update platform: darwin. Supported platforms: win, mac, linux.',
    );
  });
});
