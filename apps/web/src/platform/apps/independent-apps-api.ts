import { useEffect, useState } from 'react';

import { apiFetchJson } from '@/src/platform/api/client';
import type { ApiJsonResponse } from '@/src/platform/api/types';

type Catalog = ApiJsonResponse<'/api/v1/independent-apps/catalog', 'get'>;
export type IndependentApp = Catalog['items'][number];
export type IndependentInstallation = IndependentApp['installations'][number];
export type IndependentLaunch = ApiJsonResponse<
  '/api/v1/independent-apps/launch',
  'post'
>;

export async function getIndependentApps(
  token: string,
  signal: AbortSignal,
): Promise<IndependentApp[]> {
  const items: IndependentApp[] = [];
  const seen = new Set<string>();
  let first: Catalog | null = null;
  let page = 1;
  let bytes = 0;
  while (true) {
    const data: Catalog = await apiFetchJson(
      `/api/v1/independent-apps/catalog?page=${page}&page_size=200`,
      token,
      { signal },
    );
    first ??= data;
    bytes += JSON.stringify(data).length;
    if (
      !Number.isSafeInteger(data.total) ||
      data.total < 0 ||
      data.page !== page ||
      data.page_size !== 200 ||
      data.total !== first.total ||
      !data.catalog_revision ||
      data.catalog_revision !== first.catalog_revision ||
      data.items.length !== Math.min(200, data.total - items.length) ||
      bytes > 16 * 1024 * 1024
    ) {
      throw new Error('independent-app-catalog-incomplete');
    }
    for (const item of data.items) {
      const id = item.definition.definition.app_id;
      if (seen.has(id))
        throw new Error('independent-app-registration-duplicate');
      seen.add(id);
      items.push(item);
    }
    if (items.length === data.total) return items;
    page += 1;
  }
}

export function useIndependentApps(token: string | null) {
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{
    token: string;
    items: IndependentApp[];
    failed: boolean;
  } | null>(null);
  useEffect(() => {
    const update = () => setRefresh((value) => value + 1);
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') update();
    }, 30000);
    window.addEventListener('focus', update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', update);
    };
  }, []);
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    let active = true;
    void getIndependentApps(token, controller.signal)
      .then((items) => {
        if (active) setResult({ token, items, failed: false });
      })
      .catch(() => {
        if (active) setResult({ token, items: [], failed: true });
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [token, refresh]);
  const current = result?.token === token ? result : null;
  return {
    items: current?.items ?? [],
    loading: !!token && !current,
    failed: current?.failed ?? false,
  };
}

export function issueIndependentLaunch(
  token: string,
  installationId: string,
  challenge: string,
  signal: AbortSignal,
) {
  return apiFetchJson<IndependentLaunch>(
    '/api/v1/independent-apps/launch',
    token,
    {
      method: 'POST',
      signal,
      body: JSON.stringify({
        installation_id: installationId,
        code_challenge: challenge,
      }),
    },
  );
}

export function independentAppName(item: IndependentApp, locale: string) {
  const display = item.definition.definition.display;
  return display.translations?.[locale] ?? display.name;
}
