import { Button, Dialog, Input } from '@miy/ui';
import { useEffect, useId, useState } from 'react';
import { api, type Detail } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';

type Option = components['schemas']['TaskEnvironmentOption'];
type Worktree = components['schemas']['TaskWorktreeOption'];
type Kind = Option['kind'];
export const environmentLabels: Record<Kind, Copy> = {
  general: 'General task',
  development: 'Work in development',
  branch: 'Work in a new branch',
  existing_branch: 'Work in an existing branch',
  production: 'Work in production',
};
const descriptions: Record<Kind, Copy> = {
  general: 'Talk, research, organize documents or ask Codex to handle a task.',
  development:
    'Continue development and maintenance in the current development checkout.',
  branch:
    'Create a branch and prepare its settings and dependencies in a separate workspace.',
  existing_branch:
    'Continue in an existing worktree, keeping its changes, settings and dependencies.',
  production:
    'Inspect the production checkout in read-only mode. Changes and deployment follow a separate approval process.',
};

export function NewTaskDialog({
  open,
  onOpenChange,
  t,
  created,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  t: Translate;
  created: (task: Detail, prompt: string) => void;
}) {
  const formId = useId();
  const [options, setOptions] = useState<Option[] | null>(null);
  const [kind, setKind] = useState<Kind>('general');
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [branch, setBranch] = useState('');
  const [worktrees, setWorktrees] = useState<Worktree[] | null>(null);
  const [existingBranch, setExistingBranch] = useState('');
  const [worktreeError, setWorktreeError] = useState<string | null>(null);
  const [worktreeAttempt, setWorktreeAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setOptions(null);
    setError(null);
    void api<Option[]>(
      '/task-environments',
      undefined,
      'GET',
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        setOptions(value);
        setKind((current) =>
          value.some((item) => item.kind === current && item.available)
            ? current
            : (value.find((item) => item.available)?.kind ?? current),
        );
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError('Could not load task environments.');
      });
    return () => controller.abort();
  }, [open, attempt]);
  useEffect(() => {
    if (!open || kind !== 'existing_branch') return;
    const controller = new AbortController();
    setWorktrees(null);
    setWorktreeError(null);
    void api<Worktree[]>(
      '/task-environments/worktrees',
      undefined,
      'GET',
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setWorktrees(value);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setWorktreeError(errorCopy(reason));
      });
    return () => controller.abort();
  }, [open, kind, worktreeAttempt]);
  const selected = options?.find((item) => item.kind === kind);
  const selectedWorktree = worktrees?.find(
    (item) => item.branch === existingBranch,
  );
  const canCreate =
    selected?.available &&
    (kind !== 'existing_branch' || selectedWorktree?.available);
  const projectRoot = options?.find((item) => item.kind === 'general')?.root;
  const relativePath = (root: string | null) =>
    root === projectRoot
      ? './'
      : projectRoot && root?.startsWith(projectRoot + '/')
        ? './' + root.slice(projectRoot.length + 1)
        : root;
  const displayPath = (option: Option) => {
    const path = relativePath(option.root);
    return ['branch', 'existing_branch'].includes(option.kind) && path
      ? path + '/…'
      : path;
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value);
      }}
      title={t('New task')}
      closeLabel={t('Close')}
      contentClassName="new-task-dialog"
      maxWidth="max-w-6xl"
      actions={
        <Button
          variant="primary"
          type="submit"
          form={formId}
          fullWidth
          disabled={busy || !canCreate}
        >
          {t(busy ? 'Creating task…' : 'Open task')}
        </Button>
      }
    >
      <form
        id={formId}
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canCreate || busy) return;
          setBusy(true);
          setError(null);
          void api<Detail>('/tasks', {
            title:
              title.trim() ||
              prompt.trim().split('\n')[0].slice(0, 200) ||
              t('New task'),
            environment: kind,
            ...(kind === 'branch' && branch.trim()
              ? { branch_name: branch.trim() }
              : {}),
            ...(kind === 'existing_branch'
              ? { branch_name: existingBranch }
              : {}),
          })
            .then((task) => {
              created(task, prompt);
              onOpenChange(false);
              setTitle('');
              setPrompt('');
              setBranch('');
              setExistingBranch('');
            })
            .catch((reason) => setError(errorCopy(reason)))
            .finally(() => setBusy(false));
        }}
      >
        <fieldset className="task-environment-fieldset" disabled={busy}>
          <legend>{t('Where would you like to work?')}</legend>
          {!options && !error && (
            <p role="status">{t('Loading task environments…')}</p>
          )}
          <div className="task-environment-options">
            {options?.map((option) => (
              <label
                key={option.kind}
                className="task-environment-choice"
                data-selected={kind === option.kind}
                data-disabled={!option.available}
              >
                <input
                  type="radio"
                  name="task-environment"
                  value={option.kind}
                  checked={kind === option.kind}
                  disabled={!option.available}
                  onChange={() => setKind(option.kind)}
                />
                <span>
                  <strong>{t(environmentLabels[option.kind])}</strong>
                  <span>{t(descriptions[option.kind])}</span>
                  {option.root && (
                    <code title={option.root}>{displayPath(option)}</code>
                  )}
                  {!option.available && (
                    <span>
                      {t(
                        'This environment is not configured or is unavailable.',
                      )}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {kind === 'existing_branch' && selected?.available && (
          <div className="stack task-worktree-selection">
            <label htmlFor="task-existing-branch">
              {t('Existing worktree branch')}
            </label>
            <select
              id="task-existing-branch"
              value={existingBranch}
              disabled={busy || !worktrees?.length}
              onChange={(event) => setExistingBranch(event.target.value)}
            >
              <option value="">{t('Select a branch')}</option>
              {worktrees?.map((item) => (
                <option
                  key={item.branch}
                  value={item.branch}
                  disabled={!item.available}
                >
                  {item.branch}
                  {!item.available
                    ? ` — ${t(item.reason === 'task_environment_not_ready' ? 'Environment not ready' : 'Unavailable')}`
                    : ''}
                </option>
              ))}
            </select>
            {!worktrees && !worktreeError && (
              <p role="status">{t('Loading worktree branches…')}</p>
            )}
            {worktrees?.length === 0 && (
              <p role="status">
                {t(
                  'No existing worktree branches. Create a new branch to start.',
                )}
              </p>
            )}
            {selectedWorktree && (
              <code title={selectedWorktree.root}>
                {relativePath(selectedWorktree.root)}
              </code>
            )}
            <p className="muted">
              {t(
                'This opens a new conversation in the selected worktree. Open the previous task from work history to keep its conversation.',
              )}
            </p>
            {worktreeError && <p role="alert">{t(worktreeError as Copy)}</p>}
            <Button
              type="button"
              disabled={busy}
              onClick={() => setWorktreeAttempt((value) => value + 1)}
            >
              {t('Refresh branch list')}
            </Button>
          </div>
        )}
        {kind === 'branch' && selected?.available && (
          <>
            <label htmlFor="task-branch-name">
              {t('Branch name (optional)')}
            </label>
            <Input
              id="task-branch-name"
              value={branch}
              maxLength={100}
              disabled={busy}
              onChange={(event) => setBranch(event.target.value)}
            />
            <p className="muted">
              {t('Base branch')}: <code>{selected.base_ref}</code>.{' '}
              {t(
                'An empty name generates a unique branch. Work starts after environment preparation.',
              )}
            </p>
          </>
        )}
        <label htmlFor="task-initial-prompt">
          {t('What would you like to do?')}
        </label>
        <textarea
          id="task-initial-prompt"
          className="task-initial-prompt"
          value={prompt}
          disabled={busy}
          maxLength={32000}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={t(
            'Ask a question, describe a change or explain what you need.',
          )}
        />
        <label htmlFor="task-title">{t('Task name (optional)')}</label>
        <Input
          id="task-title"
          value={title}
          maxLength={200}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
        {error && <p role="alert">{t(error as Copy)}</p>}
        {!options && error && (
          <Button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            {t('Retry')}
          </Button>
        )}
      </form>
    </Dialog>
  );
}

export function TaskEnvironmentStatus({
  task,
  t,
  refresh,
}: {
  task: Detail;
  t: Translate;
  refresh: () => void;
}) {
  const value = task.context?.task_environment;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (
    !value ||
    typeof value !== 'object' ||
    !('kind' in value) ||
    !(String(value.kind) in environmentLabels)
  )
    return null;
  const meta = value as {
    kind: Kind;
    branch?: string;
    preparation?: { state: string; step: string; error_code?: string };
  };
  const preparation = meta.preparation;
  return (
    <div className="task-environment-status">
      <strong>{t(environmentLabels[meta.kind])}</strong>
      {meta.branch && (
        <span>
          {t('Branch')}: <code>{meta.branch}</code>
        </span>
      )}
      <code title={task.root}>{task.root}</code>
      {meta.kind === 'production' && <span>{t('Read-only inspection')}</span>}
      {preparation && preparation.state !== 'ready' && (
        <div role={preparation.state === 'failed' ? 'alert' : 'status'}>
          <p>
            {t(
              preparation.state === 'failed'
                ? 'Environment preparation failed. Retry preparation to continue.'
                : preparation.step === 'branch'
                  ? 'Preparing the new branch…'
                  : 'Preparing settings and dependencies…',
            )}
          </p>
          {preparation.state === 'failed' && (
            <Button
              disabled={busy}
              onClick={() => {
                setBusy(true);
                setError(null);
                void api(`/tasks/${task.id}/prepare`, {})
                  .then(refresh)
                  .catch((reason) => setError(errorCopy(reason)))
                  .finally(() => setBusy(false));
              }}
            >
              {t('Retry environment preparation')}
            </Button>
          )}
        </div>
      )}
      {error && <p role="alert">{t(error as Copy)}</p>}
    </div>
  );
}
