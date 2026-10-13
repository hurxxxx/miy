import { MergeRequest, type MergeRequestData } from './merge-request';
import { Button, Input } from '@miy/ui';
import {
  ChevronDown,
  ChevronRight,
  GitBranch,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
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
  onMerge,
  busy = false,
}: {
  onMerge?: (data: MergeRequestData) => Promise<boolean>;
  busy?: boolean;
  task: Detail;
  git: ReturnType<typeof useGitState>;
  locale: Locale;
  onError: (error: unknown) => void;
  t: Translate;
}) {
  const [root, setRoot] = useState('');
  const [linking, setLinking] = useState(false);
  const [saving, setSaving] = useState(false);
  const formId = useId();
  const canLink =
    !task.context?.source_binding &&
    !task.context?.app_id &&
    !task.context?.project_id;
  const changeLink = async (id?: string) => {
    if (saving) return;
    setSaving(true);
    try {
      await api(
        `/tasks/${task.id}/git-links${id ? `/${id}` : ''}`,
        id ? undefined : { root: root.trim() },
        id ? 'DELETE' : 'POST',
      );
      if (!id) {
        setRoot('');
        setLinking(false);
      }
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
        {canLink && (
          <Button
            variant="secondary"
            aria-expanded={linking}
            aria-controls={formId}
            onClick={() => setLinking(!linking)}
          >
            <Plus size={14} aria-hidden="true" />
            {t('Link branch or worktree')}
          </Button>
        )}
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
      {canLink && linking && (
        <form
          id={formId}
          className="git-link-form stack"
          onSubmit={(event) => {
            event.preventDefault();
            void changeLink();
          }}
        >
          <p className="context-note">
            {t(
              'Enter a checkout folder to display its current branch and changes.',
            )}
          </p>
          <label>
            {t('Git checkout path')}
            <Input
              autoFocus
              value={root}
              maxLength={2048}
              placeholder={task.root}
              disabled={saving}
              onChange={(event) => setRoot(event.target.value)}
            />
          </label>
          <div className="git-summary">
            <Button type="submit" disabled={saving || !root.trim()}>
              {t('Link workspace')}
            </Button>
            <Button
              variant="ghost"
              disabled={saving}
              onClick={() => setLinking(false)}
            >
              {t('Cancel')}
            </Button>
          </div>
        </form>
      )}
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
          busy={saving || busy}
          onMerge={canLink ? onMerge : undefined}
        />
      ))}
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
  onMerge,
}: {
  task: Detail;
  link: GitLink;
  initiallyOpen: boolean;
  locale: Locale;
  t: Translate;
  onError: (error: unknown) => void;
  unlink?: () => void;
  onMerge?: (data: MergeRequestData) => Promise<boolean>;
  busy: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const bodyId = useId();
  const state = link.state;
  return (
    <div className="git-checkout">
      <div className="git-checkout-header">
        <button
          type="button"
          className="git-checkout-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen(!open)}
        >
          {open ? (
            <ChevronDown size={14} aria-hidden="true" />
          ) : (
            <ChevronRight size={14} aria-hidden="true" />
          )}
          <GitBranch size={14} aria-hidden="true" />
          <strong>
            {state
              ? (state.branch ??
                `${t('Detached HEAD')} · ${state.head?.slice(0, 8) ?? t('No commits')}`)
              : t('Workspace unavailable')}
          </strong>
          <span>{state && `${t('Changed files')} ${state.changed}`}</span>
          <code className="workspace-path">{link.root}</code>
        </button>
        {unlink && (
          <Button
            className="git-checkout-unlink"
            variant="ghost"
            disabled={busy}
            aria-label={`${t('Unlink workspace')}: ${link.root}`}
            title={t('Unlinking keeps the branch and files intact.')}
            onClick={unlink}
          >
            {t('Unlink workspace')}
          </Button>
        )}
      </div>
      {open && (
        <div id={bodyId} className="stack git-checkout-body">
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
              {onMerge && (
                <MergeRequest
                  task={task}
                  linkId={link.id}
                  refreshToken={state.checked_at}
                  busy={busy}
                  t={t}
                  onMerge={onMerge}
                />
              )}
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
        </div>
      )}
    </div>
  );
}
