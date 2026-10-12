import { useEffect, useState } from 'react';
import { api, type Task } from './api';

// Search the persisted overview, including work older than the recent projection.
export function useTaskSearch(
  tasks: Task[],
  query: string,
  templateId?: string | null,
  retry = 0,
  enabled = true,
  scope?: { projectId?: string; appId?: string },
) {
  const [search, setSearch] = useState({
    key: '',
    rows: [] as Task[],
    loading: false,
    failed: false,
    checkedAt: null as number | null,
  });
  const projectId = scope?.projectId;
  const appId = scope?.appId;
  const remote = !!query || !!templateId || !!projectId || !!appId;
  const key = JSON.stringify([templateId ?? null, query, projectId, appId]);
  useEffect(() => {
    if (!enabled || !remote) return;
    const controller = new AbortController();
    setSearch((prior) => ({
      key,
      rows: prior.key === key ? prior.rows : [],
      loading: true,
      failed: false,
      checkedAt: prior.key === key ? prior.checkedAt : null,
    }));
    const timer = window.setTimeout(() => {
      void api<Task[]>(
        `/overview?search=${encodeURIComponent(query)}${templateId ? `&template_id=${encodeURIComponent(templateId)}` : ''}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}${appId ? `&app_id=${encodeURIComponent(appId)}` : ''}`,
        undefined,
        'GET',
        controller.signal,
      )
        .then((rows) => {
          if (!controller.signal.aborted)
            setSearch({
              key,
              rows,
              loading: false,
              failed: false,
              checkedAt: Date.now(),
            });
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setSearch((prior) => ({ ...prior, loading: false, failed: true }));
        });
    }, 200);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [enabled, remote, key, query, templateId, tasks, retry, projectId, appId]);
  return { remote, key, search };
}
