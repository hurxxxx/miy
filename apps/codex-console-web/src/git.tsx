import { Button, Input } from '@miy/ui';
import { GitBranch, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Detail, type GitState } from './api';
import { type Locale, type Translate } from './i18n';
import { Changes } from './views';
import type { components } from './api.generated';
type GitLink = components['schemas']['TaskGitLinkOut'];

export function useGitState(task: Detail | null) {
  const [links, setLinks] = useState<GitLink[]>([]);
  const state = links.find((link) => link.state)?.state ?? null;
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const sequence = useRef(0);
  const id = task?.id;
  const selectedId = useRef(id);
  selectedId.current = id;
  const root = task?.root;
  const status = task?.status;
  const load = useCallback(async () => {
    if (!id || selectedId.current !== id) return;
    const current = ++sequence.current;
    setLoading(true);
    try {
      const next = await api<GitLink[]>(`/tasks/${id}/git-links`);
      if (current !== sequence.current || selectedId.current !== id) return;
      if (!Array.isArray(next))
        throw new Error('Invalid Git workspace response');
      setLinks(next);
      setFailed(false);
    } catch {
      if (current === sequence.current) {
        setLinks([]);
        setFailed(true);
      }
    } finally {
      if (current === sequence.current) setLoading(false);
    }
  }, [id, root]);
  useEffect(() => {
    setLinks([]);
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    const visible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      sequence.current++;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [load, status]);
  return { state, links, failed, loading, refresh: load };
}

export function GitSummary({
  state,
  t,
}: {
  state: GitState | null;
  t: Translate;
}) {
  if (!state || state.available === false) return null;
  return (
    <div className="git-summary" role="group" aria-label={t('Git workspace')}>
      <GitBranch size={14} aria-hidden="true" />
      <strong>{state.branch ?? t('Detached HEAD')}</strong>
      <span>
        {t('Changed files')} {state.changed}
      </span>
    </div>
  );
}

export function GitWorkspace({
  task,
  git,
  locale,
  t,
  onError,
}: {
  task: Detail;
  git: ReturnType<typeof useGitState>;
  locale: Locale;
  onError: (error: unknown) => void;
  t: Translate;
}) {
  const [root, setRoot] = useState('');
  const [saving, setSaving] = useState(false);
  const changeLink = async (id?: string) => {
    if (saving) return;
    setSaving(true);
    try {
      await api(
        `/tasks/${task.id}/git-links${id ? `/${id}` : ''}`,
        id ? undefined : { root: root.trim() },
        id ? 'DELETE' : 'POST',
      );
      if (!id) setRoot('');
      await git.refresh();
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div
      className="git-workspace stack"
      role="group"
      aria-label={t('Git workspace')}
    >
      <div className="git-summary">
        <h2>
          {t('Task workspaces')} · {git.links.length}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Refresh Git state')}
          disabled={git.loading}
          onClick={() => void git.refresh()}
        >
          <RefreshCw size={14} />
        </Button>
      </div>
      <p className="context-note">
        {t('Changes include all current edits in each linked checkout.')}
      </p>
      {git.failed ? (
        <p role="alert">{t('Could not load Git state.')}</p>
      ) : (
        !git.links.length && (
          <p>
            {t(
              git.loading
                ? 'Loading Git state…'
                : 'No Git workspace linked to this task.',
            )}
          </p>
        )
      )}
      {git.links.map((link, index) => (
        <GitCheckout
          key={`${task.id}:${link.id}`}
          task={task}
          link={link}
          initiallyOpen={index === 0 || !!link.state?.changed}
          locale={locale}
          t={t}
          onError={onError}
          unlink={
            link.source === 'initial'
              ? undefined
              : () => void changeLink(link.id)
          }
          busy={saving}
        />
      ))}
      {!task.context?.source_binding &&
        !task.context?.app_id &&
        !task.context?.project_id && (
          <details className="git-link-form">
            <summary>{t('Link workspace to task')}</summary>
            <form
              className="stack"
              onSubmit={(event) => {
                event.preventDefault();
                void changeLink();
              }}
            >
              <label>
                {t('Git checkout path')}
                <Input
                  value={root}
                  maxLength={2048}
                  placeholder={task.root}
                  onChange={(event) => setRoot(event.target.value)}
                />
              </label>
              <Button type="submit" disabled={saving || !root.trim()}>
                {t('Link workspace')}
              </Button>
            </form>
          </details>
        )}
    </div>
  );
}

function GitCheckout({
  task,
  link,
  initiallyOpen,
  locale,
  t,
  onError,
  unlink,
  busy,
}: {
  task: Detail;
  link: GitLink;
  initiallyOpen: boolean;
  locale: Locale;
  t: Translate;
  onError: (error: unknown) => void;
  unlink?: () => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const state = link.state;
  return (
    <details
      className="git-checkout"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <GitBranch size={14} aria-hidden="true" />
        <strong>
          {state
            ? (state.branch ??
              `${t('Detached HEAD')} · ${state.head?.slice(0, 8) ?? t('No commits')}`)
            : t('Workspace unavailable')}
        </strong>
        <span>{state && `${t('Changed files')} ${state.changed}`}</span>
        <code className="workspace-path">{link.root}</code>
      </summary>
      {open && (
        <div className="stack git-checkout-body">
          {state ? (
            <>
              <span>
                {t('Staged')} {state.staged} · {t('Unstaged')} {state.unstaged}{' '}
                · {t('Untracked')} {state.untracked}
              </span>
              {state.conflicts > 0 && (
                <span className="danger">
                  {t('Conflicts')} {state.conflicts}
                </span>
              )}
              <span>
                {state.upstream
                  ? `${state.upstream} · ↑${state.ahead ?? '?'} ↓${state.behind ?? '?'}`
                  : t('No tracking branch')}
              </span>
              <small>
                {t(
                  'Remote counts use local tracking refs; no automatic fetch.',
                )}{' '}
                · {t('Checked')}{' '}
                {new Date(state.checked_at).toLocaleTimeString(locale)}
              </small>
              <Changes
                key={`${task.id}:${link.id}`}
                task={task}
                linkId={link.id}
                refreshToken={state.checked_at}
                t={t}
                onError={onError}
              />
            </>
          ) : (
            <p role="status">{t('Workspace unavailable')}</p>
          )}
          {unlink && (
            <Button variant="ghost" disabled={busy} onClick={unlink}>
              {t('Unlink workspace')}
            </Button>
          )}
        </div>
      )}
    </details>
  );
}
