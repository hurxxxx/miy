import { Button, Input } from '@miy/ui';
import { useEffect, useState } from 'react';
import { api } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';
import { PageLayout } from './page-layout';

type Tool = components['schemas']['ToolOut'];
const scopeCopy: Record<Tool['scope'], Copy> = {
  host: 'General and core development tasks',
  app_development: 'App development tasks',
  app_delivery: 'App delivery tasks',
  app_registration: 'App registration tasks',
};
const purpose: Record<string, Copy> = {
  miy_task_git: 'Link task branches and worktrees',
  miy_task_timeline: 'Record work summaries and check development merges',
  miy_app_source: 'Inspect and save local app changes',
  miy_app_delivery: 'Inspect and deliver a development app',
  miy_app_registration: 'Register a personal app',
};
export function ToolCatalog({ t }: { t: Translate }) {
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [error, setError] = useState<Copy | null>(null);
  const [query, setQuery] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void api<Tool[]>('/tool-catalog', undefined, 'GET', controller.signal)
      .then(setTools)
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(errorCopy(e instanceof Error ? e.message : String(e)));
      });
    return () => controller.abort();
  }, [attempt]);
  const filtered = tools?.filter((tool) =>
    `${tool.name} ${t(purpose[tool.name] ?? 'Tools')} ${t(scopeCopy[tool.scope])} ${tool.description}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <PageLayout
      title={t('Codex tools')}
      description={t(
        'Tools Workbench provides to Codex, with their purpose and input contract.',
      )}
    >
      <p className="context-note">
        {t(
          'Tools are selected when a new conversation starts. Existing conversations may not have newly added tools. Codex built-in tools and external MCP tools are managed separately.',
        )}
      </p>
      <Input
        aria-label={t('Search tools')}
        placeholder={t('Search tools')}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {error && (
        <p role="alert">
          {t(error)}{' '}
          <Button onClick={() => setAttempt(attempt + 1)}>{t('Retry')}</Button>
        </p>
      )}
      {!tools && !error && <p role="status">{t('Loading…')}</p>}
      <div className="tool-catalog-grid">
        {filtered?.map((tool) => (
          <article className="tool-catalog-card stack" key={tool.name}>
            <span className="muted">{t(scopeCopy[tool.scope])}</span>
            <h2>{t(purpose[tool.name] ?? 'Tools')}</h2>
            <code>{tool.name}</code>
            <details>
              <summary>{t('Tool instructions and inputs')}</summary>
              <p>{tool.description}</p>
              <pre>{JSON.stringify(tool.input_schema, null, 2)}</pre>
            </details>
          </article>
        ))}
      </div>
      {filtered?.length === 0 && <p>{t('No matching tools.')}</p>}
    </PageLayout>
  );
}
