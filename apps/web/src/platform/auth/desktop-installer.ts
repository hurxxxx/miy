import {
  miyDesktopInstallerUrl,
  type MIYDesktopUpdatePlatform,
} from '@miy/contracts/miy-desktop-update-feed';

export type DesktopInstallPlatform = MIYDesktopUpdatePlatform;

export type DesktopInstallerEnv = Partial<{
  VITE_MIY_DESKTOP_INSTALLER_URL: string;
  VITE_MIY_DESKTOP_INSTALLER_URL_WIN: string;
  VITE_MIY_DESKTOP_INSTALLER_URL_MAC: string;
  VITE_MIY_DESKTOP_INSTALLER_URL_LINUX: string;
}>;

export type DesktopPlatformSignal = {
  platform?: string | null;
  userAgent?: string | null;
};

export type DesktopInstallerDownload = {
  href: string;
  fileName: string;
};

export type DesktopInstallerIcon = 'monitor' | 'apple' | 'terminal';

export type DesktopInstallerPlatformDefinition = {
  platform: DesktopInstallPlatform;
  icon: DesktopInstallerIcon;
  titleKey: string;
  descriptionKey: string;
  guideKey: string;
};

export type DesktopInstallerRow = DesktopInstallerPlatformDefinition & {
  installerUrl: string;
  isCurrent: boolean;
};

export const DEFAULT_DESKTOP_INSTALLER_URLS: Record<
  DesktopInstallPlatform,
  string
> = {
  win: miyDesktopInstallerUrl('win'),
  mac: miyDesktopInstallerUrl('mac'),
  linux: miyDesktopInstallerUrl('linux'),
};

export const DESKTOP_INSTALLER_PLATFORMS: DesktopInstallerPlatformDefinition[] =
  [
    {
      platform: 'win',
      icon: 'monitor',
      titleKey: 'settings.miyDesktopWindowsTitle',
      descriptionKey: 'settings.miyDesktopWindowsDescription',
      guideKey: 'settings.miyDesktopWindowsGuide',
    },
    {
      platform: 'mac',
      icon: 'apple',
      titleKey: 'settings.miyDesktopMacTitle',
      descriptionKey: 'settings.miyDesktopMacDescription',
      guideKey: 'settings.miyDesktopMacGuide',
    },
    {
      platform: 'linux',
      icon: 'terminal',
      titleKey: 'settings.miyDesktopLinuxTitle',
      descriptionKey: 'settings.miyDesktopLinuxDescription',
      guideKey: 'settings.miyDesktopLinuxGuide',
    },
  ];

export const DESKTOP_INSTALLER_URLS = resolveDesktopInstallerUrls(
  import.meta.env as DesktopInstallerEnv,
);

export class DesktopInstallerCatalog {
  constructor(
    private readonly platforms: DesktopInstallerPlatformDefinition[] = DESKTOP_INSTALLER_PLATFORMS,
  ) {}

  rows(
    urls: Record<DesktopInstallPlatform, string>,
    currentPlatform: DesktopInstallPlatform,
  ): DesktopInstallerRow[] {
    return this.platforms.map((item) => ({
      ...item,
      installerUrl: urls[item.platform],
      isCurrent: item.platform === currentPlatform,
    }));
  }
}

export function resolveDesktopInstallerUrls(
  env: DesktopInstallerEnv,
): Record<DesktopInstallPlatform, string> {
  return {
    win:
      env.VITE_MIY_DESKTOP_INSTALLER_URL_WIN ??
      env.VITE_MIY_DESKTOP_INSTALLER_URL ??
      DEFAULT_DESKTOP_INSTALLER_URLS.win,
    mac:
      env.VITE_MIY_DESKTOP_INSTALLER_URL_MAC ??
      DEFAULT_DESKTOP_INSTALLER_URLS.mac,
    linux:
      env.VITE_MIY_DESKTOP_INSTALLER_URL_LINUX ??
      DEFAULT_DESKTOP_INSTALLER_URLS.linux,
  };
}

export function detectDesktopInstallPlatform(
  signal: DesktopPlatformSignal = browserDesktopPlatformSignal(),
): DesktopInstallPlatform {
  const platform = (signal.platform ?? '').toLowerCase();
  const userAgent = (signal.userAgent ?? '').toLowerCase();
  if (platform.includes('mac') || userAgent.includes('mac os')) {
    return 'mac';
  }
  if (platform.includes('linux') || userAgent.includes('linux')) {
    return 'linux';
  }
  return 'win';
}

export function buildDesktopInstallerRows(
  urls: Record<DesktopInstallPlatform, string> = DESKTOP_INSTALLER_URLS,
  currentPlatform: DesktopInstallPlatform = detectDesktopInstallPlatform(),
): DesktopInstallerRow[] {
  return new DesktopInstallerCatalog().rows(urls, currentPlatform);
}

export function resolveDesktopInstallerDownload(
  installerUrl: string,
  locationHref: string,
): DesktopInstallerDownload {
  const resolvedUrl = new URL(installerUrl, locationHref);
  return {
    href: resolvedUrl.href,
    fileName: decodeURIComponent(
      resolvedUrl.pathname.split('/').pop() ?? 'MIY-Desktop',
    ),
  };
}

export function downloadDesktopInstaller(
  installerUrl: string,
  documentRef: Document = document,
  locationHref: string = window.location.href,
) {
  const download = resolveDesktopInstallerDownload(installerUrl, locationHref);
  const anchor = documentRef.createElement('a');
  anchor.href = download.href;
  anchor.download = download.fileName;
  documentRef.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function browserDesktopPlatformSignal(): DesktopPlatformSignal {
  if (typeof window === 'undefined') {
    return {};
  }
  return {
    platform: window.navigator.platform,
    userAgent: window.navigator.userAgent,
  };
}
