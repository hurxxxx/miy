import { Button, Dialog, DropdownMenu, Input } from '@miy/ui';
import {
  Folder,
  History,
  ListTodo,
  MoreHorizontal,
  Play,
  Plus,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Detail } from './api';
import type { components } from './api.generated';
import type { Translate } from './i18n';
import { EmptyState, PageLayout } from './page-layout';

type Definition = components['schemas']['TemplateDefinition'];
type Template = components['schemas']['TemplateOut'];
type Catalog = components['schemas']['TemplateCatalog'];
const fresh = (): Definition => ({
  name: '',
  description: '',
  directory: '.',
  context: '',
  references: [],
  skills: [],
  prompt: '',
  variables: [],
  stage: 'implement',
  permissions: 'ask',
  isolate: false,
  shared_resources: true,
  model: null,
  effort: null,
});

export function Templates({
  t,
  openTask,
  openHistory,
  onError,
}: {
  t: Translate;
  openTask: (id: string) => void;
  openHistory: (id: string) => void;
  onError: (e: unknown) => void;
}) {
  const [rows, setRows] = useState<Template[]>([]);
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<Template | 'new' | null>(null);
  const [definition, setDefinition] = useState<Definition>(fresh);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const [running, setRunning] = useState<Template | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const launch = useRef<{ id: string; key: string } | null>(null);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api<Template[]>(`/templates?archived=${archived}`));
      setFailed(false);
    } catch (e) {
      setFailed(true);
      onError(e);
    } finally {
      setLoading(false);
    }
  }, [archived, onError]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!editing) return;
    const controller = new AbortController();
    setCatalog(null);
    setCatalogError(false);
    const timer = window.setTimeout(() => {
      void api<Catalog>(
        `/templates/catalog?directory_name=${encodeURIComponent(definition.directory ?? '.')}`,
        undefined,
        'GET',
        controller.signal,
      )
        .then(setCatalog)
        .catch(() => {
          if (!controller.signal.aborted) setCatalogError(true);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [editing, definition.directory]);
  const change = <K extends keyof Definition>(key: K, value: Definition[K]) =>
    setDefinition((d) => ({ ...d, [key]: value }));
  const edit = (row: Template | null, copy = false) => {
    setDefinition(
      row
        ? structuredClone({
            ...row.definition,
            name: copy
              ? `${row.definition.name} · ${t('Copy')}`
              : row.definition.name,
          })
        : fresh(),
    );
    setEditing(!row || copy ? 'new' : row);
  };
  const start = async (row: Template, input: Record<string, string>) => {
    if (busy) return;
    setBusy(true);
    const key = JSON.stringify([row.id, row.version, input]);
    if (launch.current?.key !== key)
      launch.current = { key, id: crypto.randomUUID() };
    try {
      const task = await api<Detail>(`/templates/${row.id}/run`, {
        launch_id: launch.current.id,
        version: row.version,
        values: input,
      });
      launch.current = null;
      setRunning(null);
      openTask(task.id);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const chooseRun = (row: Template) => {
    const input = Object.fromEntries(
      (row.definition.variables ?? []).map((v) => [v.name, v.default ?? '']),
    );
    if (
      (row.definition.variables ?? []).some(
        (v) => v.required !== false && !input[v.name]?.trim(),
      )
    ) {
      setValues(input);
      setRunning(row);
    } else {
      void start(row, input);
    }
  };
  const archive = async (row: Template) => {
    setBusy(true);
    try {
      await api(
        `/templates/${row.id}`,
        {
          version: row.version,
          definition: row.definition,
          archived: !row.archived,
        },
        'PUT',
      );
      await load();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  const query = search.trim().toLocaleLowerCase();
  const visible = rows.filter((row) =>
    `${row.definition.name} ${row.definition.description}`
      .toLocaleLowerCase()
      .includes(query),
  );
  return (
    <PageLayout
      className="templates-view"
      title={t('Task templates')}
      description={t(
        'Save the context once. Start each run in a new Codex session.',
      )}
      actions={
        <Button variant="primary" size="comfortable" onClick={() => edit(null)}>
          <Plus size={16} aria-hidden="true" />
          {t('Create template')}
        </Button>
      }
    >
      <div className="list-controls">
        <div className="list-toolbar">
          <Input
            aria-label={t('Search templates')}
            placeholder={t('Search templates by name or description')}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <label className="inline-check">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />
            {t('Show archived templates')}
          </label>
        </div>
        <p className="list-count" role="status">
          {t('Templates shown')}: {loading ? '…' : visible.length}
        </p>
      </div>
      {loading && <p role="status">{t('Loading templates')}</p>}
      {failed && <Button onClick={() => void load()}>{t('Retry')}</Button>}
      {!loading && !failed && !visible.length && (
        <EmptyState
          icon={<ListTodo size={28} />}
          title={t(query ? 'No matching templates' : 'No templates yet')}
          description={t(
            'Save the context once. Start each run in a new Codex session.',
          )}
          action={
            query ? (
              <Button size="comfortable" onClick={() => setSearch('')}>
                {t('Clear filters')}
              </Button>
            ) : (
              <Button size="comfortable" onClick={() => edit(null)}>
                {t('Create template')}
              </Button>
            )
          }
        />
      )}
      <div className="template-list">
        {visible.length > 0 && (
          <div className="template-columns list-columns" aria-hidden="true">
            <span>{t('Task template')}</span>
            <span>{t('Execution settings')}</span>
            <span>{t('Actions')}</span>
          </div>
        )}
        {visible.map((row) => (
          <article className="template-row" key={row.id}>
            <div className="template-content">
              <h2>{row.definition.name}</h2>
              <p>{row.definition.description}</p>
              <details>
                <summary>{t('Request details')}</summary>
                <p className="template-prompt">{row.definition.prompt}</p>
                <p className="muted">
                  {(row.definition.skills ?? []).join(' · ')}
                </p>
              </details>
            </div>
            <div className="template-meta">
              <span className="template-mode">
                {t(row.definition.stage === 'plan' ? 'Plan' : 'Implement')} · v
                {row.version}
              </span>
              <span>
                {t(
                  row.definition.isolate
                    ? 'Isolated workspace'
                    : 'Shared workspace',
                )}
              </span>
              <div className="template-path">
                <Folder size={13} aria-hidden="true" />
                <span className="sr-only">{t('Workspace')}</span>
                <code>{row.definition.directory}</code>
              </div>
            </div>
            <div className="template-actions">
              <div className="template-primary-actions">
                {!row.archived && (
                  <Button
                    size="dense"
                    disabled={busy}
                    onClick={() => chooseRun(row)}
                  >
                    <Play size={14} aria-hidden="true" />
                    {t('Run template')}
                  </Button>
                )}
                <Button variant="ghost" onClick={() => openHistory(row.id)}>
                  <History size={15} aria-hidden="true" />
                  {t('Run history')}
                </Button>
              </div>
              <DropdownMenu
                side="bottom"
                align="end"
                contentClassName="template-action-menu"
                trigger={
                  <Button
                    className="template-more"
                    variant="ghost"
                    size="icon"
                    disabled={busy}
                    aria-label={t('Template actions')}
                  >
                    <MoreHorizontal size={18} />
                  </Button>
                }
                items={[
                  {
                    id: 'edit',
                    label: t('Edit'),
                    disabled: busy,
                    onSelect: () => edit(row),
                  },
                  {
                    id: 'duplicate',
                    label: t('Duplicate'),
                    disabled: busy,
                    onSelect: () => edit(row, true),
                  },
                  {
                    id: 'archive',
                    label: t(
                      row.archived ? 'Restore template' : 'Archive template',
                    ),
                    separatorBefore: true,
                    disabled: busy,
                    onSelect: () => void archive(row),
                  },
                ]}
              />
            </div>
          </article>
        ))}
      </div>
      <Dialog
        open={!!running}
        onOpenChange={(v) => {
          if (!v && !busy) setRunning(null);
        }}
        title={running?.definition.name ?? t('Run template')}
        closeLabel={t('Close')}
      >
        <form
          className="stack template-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (running) void start(running, values);
          }}
        >
          <p>{running?.definition.description}</p>
          {running?.definition.variables?.map((v) => (
            <label key={v.name}>
              {v.label}
              <Input
                required={v.required !== false}
                maxLength={4000}
                value={values[v.name] ?? ''}
                onChange={(e) =>
                  setValues((x) => ({ ...x, [v.name]: e.target.value }))
                }
              />
            </label>
          ))}
          <Button type="submit" variant="primary" disabled={busy}>
            {t('Run template')}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={!!editing}
        onOpenChange={(v) => {
          if (!v && !busy) setEditing(null);
        }}
        title={t(editing === 'new' ? 'Create template' : 'Edit template')}
        closeLabel={t('Close')}
        maxWidth="max-w-2xl"
        contentClassName="template-editor-dialog"
        dismissOnInteractOutside={false}
        actions={
          <Button
            form="template-editor-form"
            type="submit"
            variant="primary"
            size="comfortable"
            disabled={busy}
          >
            {t('Save template')}
          </Button>
        }
      >
        <form
          id="template-editor-form"
          className="stack template-form"
          onSubmit={(e) => {
            e.preventDefault();
            void (async () => {
              if (busy) return;
              setBusy(true);
              try {
                if (editing === 'new') await api('/templates', definition);
                else if (editing)
                  await api(
                    `/templates/${editing.id}`,
                    {
                      version: editing.version,
                      definition,
                      archived: editing.archived,
                    },
                    'PUT',
                  );
                setEditing(null);
                await load();
              } catch (error) {
                onError(error);
              } finally {
                setBusy(false);
              }
            })();
          }}
        >
          <label>
            {t('Template name')}
            <Input
              required
              maxLength={100}
              value={definition.name}
              onChange={(e) => change('name', e.target.value)}
            />
          </label>
          <label>
            {t('Description')}
            <Input
              maxLength={1000}
              value={definition.description ?? ''}
              onChange={(e) => change('description', e.target.value)}
            />
          </label>
          <label>
            {t('Working directory relative to project')}
            <Input
              required
              value={definition.directory ?? '.'}
              maxLength={1000}
              onChange={(e) => change('directory', e.target.value)}
            />
          </label>
          <label>
            {t('Prompt')}
            <textarea
              aria-label={t('Prompt')}
              required
              value={definition.prompt}
              maxLength={16000}
              onChange={(e) => change('prompt', e.target.value)}
              rows={6}
            />
          </label>
          <fieldset>
            <legend>{t('Run inputs')}</legend>
            <p className="muted">
              {t(
                'Use {{name}} in the prompt or context. Values are inserted as text.',
              )}
            </p>
            {(definition.variables ?? []).map((v, i) => (
              <div className="template-variable" key={i}>
                <Input
                  aria-label={t('Input name')}
                  required
                  pattern="[a-z][a-z0-9_]{0,39}"
                  value={v.name}
                  onChange={(e) =>
                    change(
                      'variables',
                      definition.variables!.map((x, j) =>
                        i === j ? { ...x, name: e.target.value } : x,
                      ),
                    )
                  }
                />
                <Input
                  aria-label={t('Input label')}
                  required
                  value={v.label}
                  onChange={(e) =>
                    change(
                      'variables',
                      definition.variables!.map((x, j) =>
                        i === j ? { ...x, label: e.target.value } : x,
                      ),
                    )
                  }
                />
                <Input
                  aria-label={t('Default value')}
                  value={v.default ?? ''}
                  maxLength={4000}
                  onChange={(e) =>
                    change(
                      'variables',
                      definition.variables!.map((x, j) =>
                        i === j ? { ...x, default: e.target.value } : x,
                      ),
                    )
                  }
                />
                <label className="inline-check">
                  <input
                    type="checkbox"
                    checked={v.required !== false}
                    onChange={(e) =>
                      change(
                        'variables',
                        definition.variables!.map((x, j) =>
                          i === j ? { ...x, required: e.target.checked } : x,
                        ),
                      )
                    }
                  />
                  {t('Required')}
                </label>
                <Button
                  type="button"
                  onClick={() =>
                    change(
                      'variables',
                      definition.variables!.filter((_, j) => i !== j),
                    )
                  }
                >
                  {t('Remove input')}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              disabled={(definition.variables?.length ?? 0) >= 20}
              onClick={() =>
                change('variables', [
                  ...(definition.variables ?? []),
                  {
                    name: `input${(definition.variables?.length ?? 0) + 1}`,
                    label: '',
                    required: true,
                    default: '',
                  },
                ])
              }
            >
              {t('Add input')}
            </Button>
          </fieldset>
          <label>
            {t('Additional context')}
            <textarea
              aria-label={t('Additional context')}
              value={definition.context ?? ''}
              maxLength={16000}
              onChange={(e) => change('context', e.target.value)}
              rows={3}
            />
          </label>
          <label>
            {t('Reference paths, one per line')}
            <textarea
              aria-label={t('Reference paths, one per line')}
              value={(definition.references ?? []).join('\n')}
              onChange={(e) => change('references', e.target.value.split('\n'))}
              onBlur={() =>
                change(
                  'references',
                  (definition.references ?? [])
                    .map((x) => x.trim())
                    .filter(Boolean),
                )
              }
              rows={3}
            />
          </label>
          <fieldset>
            <legend>{t('Available skills')}</legend>
            {catalogError && (
              <p role="status">
                {t(
                  'Template runner is unavailable. Saved templates can still be edited.',
                )}
              </p>
            )}
            {[
              ...new Set([
                ...(catalog?.skills ?? []).map((s) => s.name),
                ...(definition.skills ?? []),
              ]),
            ].map((name) => (
              <label className="inline-check" key={name}>
                <input
                  type="checkbox"
                  checked={definition.skills?.includes(name) ?? false}
                  onChange={(e) =>
                    change(
                      'skills',
                      e.target.checked
                        ? [...(definition.skills ?? []), name]
                        : definition.skills?.filter((x) => x !== name),
                    )
                  }
                />
                {name}
              </label>
            ))}
          </fieldset>
          <div className="template-options">
            <label>
              {t('Execution mode')}
              <select
                value={definition.stage}
                onChange={(e) =>
                  change('stage', e.target.value as 'plan' | 'implement')
                }
              >
                <option value="plan">{t('Plan')}</option>
                <option value="implement">{t('Implement')}</option>
              </select>
            </label>
            <label>
              {t('Permissions')}
              <select
                value={definition.permissions}
                onChange={(e) =>
                  change('permissions', e.target.value as 'ask' | 'yolo')
                }
              >
                <option value="ask">{t('Ask when needed')}</option>
                <option value="yolo">{t('YOLO · Full access')}</option>
              </select>
            </label>
            <label>
              {t('Model')}
              <select
                value={definition.model ?? ''}
                onChange={(e) => {
                  change('model', e.target.value || null);
                  change('effort', null);
                }}
              >
                <option value="">{t('Codex default')}</option>
                {[
                  ...new Set([
                    ...(catalog?.models ?? []).map((m) => m.model),
                    ...(definition.model ? [definition.model] : []),
                  ]),
                ].map((model) => (
                  <option key={model}>{model}</option>
                ))}
              </select>
            </label>
            <label>
              {t('Reasoning effort')}
              <select
                value={definition.effort ?? ''}
                onChange={(e) => change('effort', e.target.value || null)}
              >
                <option value="">{t('Codex default')}</option>
                {[
                  ...new Set([
                    ...(catalog?.models.find(
                      (m) =>
                        m.model === definition.model ||
                        (!definition.model && m.is_default),
                    )?.efforts ?? []),
                    ...(definition.effort ? [definition.effort] : []),
                  ]),
                ].map((e) => (
                  <option key={e}>{e}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={definition.isolate ?? false}
              onChange={(e) => change('isolate', e.target.checked)}
            />
            {t('Isolate this task for parallel work')}
          </label>
          <label className="inline-check">
            <input
              type="checkbox"
              checked={definition.shared_resources !== false}
              onChange={(e) => change('shared_resources', e.target.checked)}
            />
            {t('Serialize changes to shared server resources')}
          </label>
        </form>
      </Dialog>
    </PageLayout>
  );
}
