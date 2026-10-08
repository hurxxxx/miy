import type { IndependentApp } from '@/src/platform/apps/independent-apps-api';
import { APP_CONTRACTS } from '@miy/contracts/app-contracts';

const builtinAppIds = new Set<string>(APP_CONTRACTS.map((app) => app.app_id));

export function needsIndependentAppCatalog(appIds?: readonly string[]) {
  return !appIds || appIds.some((id) => !builtinAppIds.has(id));
}

/** Presentation scope; the catalog service still owns admission and data access. */
export function scopeIndependentAppItems(
  items: IndependentApp[],
  appIds?: readonly string[],
) {
  if (!appIds) return items;
  const allowed = new Set(appIds);
  return items.filter((item) => allowed.has(item.definition.definition.app_id));
}
