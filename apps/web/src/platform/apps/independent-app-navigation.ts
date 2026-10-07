import { APP_CONTRACT_BY_ID, type AppId } from '@miy/contracts/app-contracts';
import { buildAppHref } from '@miy/contracts/app-routes';

import { getAppsBootstrap } from './apps-api';
import {
  checkedNavigationTarget,
  independentAppPath,
  type IndependentNavigationTarget,
} from './independent-app-host';
import {
  getIndependentApps,
  independentAppName,
  type IndependentInstallation,
} from './independent-apps-api';

export interface IndependentNavigationSource {
  appId: string;
  installationId: string;
  origin: string;
  generation: number;
  entrypoint: string;
}

export interface IndependentNavigationDestination {
  target: IndependentNavigationTarget;
  path: string;
  identity: string;
  label: string;
}

function installationIdentity(
  appId: string,
  installation: IndependentInstallation,
) {
  return JSON.stringify([
    appId,
    installation.id,
    installation.origin,
    installation.generation,
    installation.release_id ?? null,
    installation.ui_entrypoint,
  ]);
}

/** Presentation only. Both catalogs are fetched anew, never read from a hook cache. */
export async function resolveIndependentNavigation({
  token,
  actorId,
  source,
  target,
  locale,
  signal,
}: {
  token: string;
  actorId: string;
  source: IndependentNavigationSource;
  target: IndependentNavigationTarget;
  locale: string;
  signal: AbortSignal;
}): Promise<IndependentNavigationDestination | null> {
  const checked = checkedNavigationTarget(target);
  if (!checked || signal.aborted) return null;
  const [bootstrap, catalog] = await Promise.all([
    getAppsBootstrap(token, signal),
    getIndependentApps(token, signal),
  ]);
  if (
    signal.aborted ||
    bootstrap.principal.kind !== 'user' ||
    bootstrap.principal.user_id !== actorId
  )
    return null;
  const currentSource = catalog
    .find((item) => item.definition.definition.app_id === source.appId)
    ?.installations.find((item) => item.id === source.installationId);
  if (
    !currentSource?.launchable ||
    currentSource.origin !== source.origin ||
    currentSource.generation !== source.generation ||
    currentSource.ui_entrypoint !== source.entrypoint
  )
    return null;
  const contract = APP_CONTRACT_BY_ID.get(checked.app_id as AppId);
  if (contract) {
    if (checked.installation_id) return null;
    const candidates = bootstrap.apps.filter(
      (item) => item.app_id === checked.app_id,
    );
    const app = candidates[0];
    if (
      candidates.length !== 1 ||
      !app?.enabled ||
      app.coming_soon ||
      app.entry_route_id !== contract.entry_route_id
    )
      return null;
    const path = buildAppHref({ routeId: contract.entry_route_id });
    return {
      target: checked,
      path,
      identity: path,
      label: app.title.slice(0, 200),
    };
  }
  // Multiple environments must never be resolved by picking the first installation.
  if (!checked.installation_id) return null;
  const item = catalog.find(
    (candidate) => candidate.definition.definition.app_id === checked.app_id,
  );
  const installation = item?.installations.find(
    (candidate) => candidate.id === checked.installation_id,
  );
  if (!item || !installation?.launchable || !installation.ui_entrypoint)
    return null;
  return {
    target: checked,
    path: independentAppPath(checked.app_id, checked.installation_id),
    identity: installationIdentity(checked.app_id, installation),
    label: independentAppName(item, locale).slice(0, 200),
  };
}
