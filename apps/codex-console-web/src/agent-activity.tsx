import * as Dialog from '@radix-ui/react-dialog';
import { Button } from '@miy/ui';
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  X,
} from 'lucide-react';
import { useLayoutEffect, useRef, useState } from 'react';
import type { Task } from './api';
import type { Copy, Translate } from './i18n';
import {
  activityGroup,
  currentStep,
  executionCount,
  rowStatus,
  type Group,
} from './agent-state';
import { AgentTree } from './management';

const sections: { id: Group; label: Copy }[] = [
  { id: 'attention', label: 'Needs attention' },
  { id: 'running', label: 'Running' },
  { id: 'waiting', label: 'Awaiting confirmation' },
  { id: 'finished', label: 'Recently finished' },
];

export function AgentActivity({
  tasks,
  checkedAt,
  failed,
  t,
  openTask,
  openAgents,
}: {
  tasks: Task[];
  checkedAt: number | null;
  failed: boolean;
  t: Translate;
  openTask: (id: string) => void;
  openAgents: () => void;
}) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const focused = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const previous = focused.current;
    if (
      !open ||
      !previous ||
      previous.isConnected ||
      document.activeElement !== document.body
    )
      return;
    // Regrouping moves cards between sections. Keep keyboard users on their task.
    const taskId =
      previous.closest<HTMLElement>('[data-task-id]')?.dataset.taskId;
    const next = Array.from(
      panel.current?.querySelectorAll<HTMLElement>('[data-task-id]') ?? [],
    )
      .find((card) => card.dataset.taskId === taskId)
      ?.querySelector<HTMLButtonElement>('.agent-open-task');
    (
      next ??
      panel.current?.querySelector<HTMLButtonElement>('#close-agent-activity')
    )?.focus();
  }, [tasks, open]);
  const groups: Record<Group, Task[]> = {
    attention: [],
    running: [],
    waiting: [],
    finished: [],
  };
  for (const task of [...tasks].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  )) {
    const group = activityGroup(task);
    if (group) groups[group].push(task);
  }
  const runningCount = tasks.reduce(
    (sum, task) => sum + executionCount(task),
    0,
  );
  const attentionCount = groups.attention.length;
  const summary = `${t('Running agents')}: ${runningCount} · ${t('Needs attention')}: ${attentionCount} · ${t('Recently finished')}: ${groups.finished.length}`;
  return (
    <Dialog.Root open={open} onOpenChange={setOpen} modal={false}>
      <Dialog.Trigger asChild>
        <button
          className="agent-activity-trigger"
          data-busy={runningCount > 0}
          data-attention={attentionCount > 0}
          aria-label={`${t('Agent activity')} · ${failed ? t('Updates delayed') : !checkedAt ? t('Loading agent activity') : summary}`}
        >
          <Activity size={16} aria-hidden="true" />
          <span className="agent-trigger-label">{t('Agents')}</span>
          <span className="agent-trigger-count">
            {checkedAt ? runningCount : '…'}
          </span>
          {attentionCount > 0 && (
            <span className="agent-trigger-alert">
              <CircleAlert size={12} aria-hidden="true" />
              {attentionCount}
            </span>
          )}
          {failed && (
            <span className="agent-trigger-alert">
              <CircleAlert size={14} aria-hidden="true" />
            </span>
          )}
        </button>
      </Dialog.Trigger>
      <span role="status" className="sr-only">
        {checkedAt ? summary : t('Loading agent activity')}
        {failed ? ` · ${t('Updates delayed')}` : ''}
      </span>
      <Dialog.Portal>
        <Dialog.Content
          ref={panel}
          onFocusCapture={(event) => {
            focused.current = event.target as HTMLElement;
          }}
          className="agent-activity-panel"
          onOpenAutoFocus={(event) => {
            // Start at the close control, not a task that could move the user away.
            event.preventDefault();
            document.getElementById('close-agent-activity')?.focus();
          }}
        >
          <header className="agent-panel-heading">
            <div>
              <Dialog.Title>{t('Agent activity')}</Dialog.Title>
              <Dialog.Description>
                {t('Follow parallel work and return to its results.')}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button
                id="close-agent-activity"
                size="icon"
                variant="ghost"
                aria-label={t('Close agent activity')}
              >
                <X size={18} />
              </Button>
            </Dialog.Close>
          </header>
          <div className="agent-panel-summary">
            <div>
              <strong>{runningCount}</strong>
              <span>{t('Running agents')}</span>
            </div>
            <div data-attention={attentionCount > 0}>
              <strong>{attentionCount}</strong>
              <span>{t('Needs attention')}</span>
            </div>
            <div>
              <strong>{groups.finished.length}</strong>
              <span>{t('Recently finished')}</span>
            </div>
          </div>
          {failed && (
            <p className="agent-update-warning">
              {t('Updates delayed. Showing the last received state.')}
            </p>
          )}
          <div className="agent-panel-list">
            {!checkedAt ? (
              <p className="agent-panel-empty">{t('Loading agent activity')}</p>
            ) : (
              !Object.values(groups).some((rows) => rows.length) && (
                <div className="agent-panel-empty">
                  <Activity size={28} />
                  <strong>{t('No agent activity yet')}</strong>
                  <p>
                    {t(
                      'Start a task or template. Its agents will appear here.',
                    )}
                  </p>
                </div>
              )
            )}
            {sections.map(
              ({ id, label }) =>
                groups[id].length > 0 && (
                  <section
                    key={id}
                    aria-label={t(label)}
                    className="agent-activity-group"
                  >
                    <h3>
                      {t(label)} <span>{groups[id].length}</span>
                    </h3>
                    {(id === 'finished'
                      ? groups[id].slice(0, 5)
                      : groups[id]
                    ).map((task) => (
                      <article
                        key={task.id}
                        data-task-id={task.id}
                        className="agent-activity-card"
                        data-state={id}
                      >
                        <button
                          className="agent-open-task"
                          onClick={() => {
                            setOpen(false);
                            openTask(task.id);
                          }}
                        >
                          <span className="agent-row-icon" aria-hidden="true">
                            {id === 'running' ? (
                              <LoaderCircle size={17} />
                            ) : id === 'attention' ? (
                              <CircleAlert size={17} />
                            ) : id === 'finished' ? (
                              <CheckCircle2 size={17} />
                            ) : (
                              <Activity size={17} />
                            )}
                          </span>
                          <span className="agent-row-main">
                            <strong>{task.title}</strong>
                            <span>
                              {t(rowStatus(task, id))} ·{' '}
                              {t(
                                task.executor === 'templates'
                                  ? 'Template run'
                                  : 'Task workspace',
                              )}
                            </span>
                          </span>
                          <ArrowUpRight size={15} aria-hidden="true" />
                        </button>
                        {id === 'running' && (
                          <p className="agent-current-step">
                            {currentStep(task, t)}
                          </p>
                        )}
                        {task.agents.length > 0 && (
                          <details className="agent-activity-details">
                            <summary>
                              {t('Agent details')}{' '}
                              <span>{task.agents.length}</span>
                            </summary>
                            <AgentTree agents={task.agents} t={t} />
                          </details>
                        )}
                        <time
                          className="agent-row-time"
                          dateTime={task.updated_at}
                        >
                          {t('Updated')}:{' '}
                          {new Date(task.updated_at).toLocaleString()}
                        </time>
                      </article>
                    ))}
                  </section>
                ),
            )}
          </div>
          <footer className="agent-panel-footer">
            <small>
              {checkedAt
                ? `${t('List refreshed')}: ${new Date(checkedAt).toLocaleTimeString()}`
                : t('Loading agent activity')}
            </small>
            <Button
              variant="ghost"
              onClick={() => {
                setOpen(false);
                openAgents();
              }}
            >
              {t('View all agents')}
              <ArrowUpRight size={14} />
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
