import type { ShellAppId } from '@/src/platform/apps/app-links';
import { APP_CONTRACT_BY_ID, type AppId } from '@miy/contracts/app-contracts';

export {
  DARK_MODE_QUERY,
  getSystemDarkModeSnapshot,
  resolveThemePreference,
  subscribeSystemDarkMode,
  type ResolvedThemePreference,
} from '@miy/platform-web/theme/document-theme';
export type AppDisplayScope = 'company' | 'personal';

export function getInitials(label: string, fallback: string): string {
  const initials = label
    .trim()
    .split(/[\s-]+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');

  return initials || fallback;
}

export function resolveAppDisplayScope(
  appId: ShellAppId,
): AppDisplayScope | null {
  const contract = APP_CONTRACT_BY_ID.get(appId as AppId);
  if (!contract) return null;
  return contract.execution_context_kind === 'personal'
    ? 'personal'
    : 'company';
}
