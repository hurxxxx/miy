import { Button } from '@miy/ui';
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  FileCode2,
  History,
  ListTodo,
  SquareTerminal,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api, record, string, type Detail } from './api';
import type { components } from './api.generated';
import { errorCopy, type Copy, type Translate } from './i18n';
import { Command } from './views';

type Entry = components['schemas']['TaskHistoryItem'];
type Page = components['schemas']['TaskHistoryPage'];
type Category = 'all' | 'execution' | 'requests' | 'tools';
const categories: { id: Category; label: Copy }[] = [
  { id: 'all', label: 'All activity' },
  { id: 'execution', label: 'Execution and progress' },
  { id: 'requests', label: 'Questions and approvals' },
  { id: 'tools', label: 'Commands and files' },
];

function title(entry: Entry): Copy {
  const details = entry.details ?? {};
  if (entry.event === 'question.pending') return 'Question requested';
  if (entry.event === 'question.sending') return 'Sending response';
  if (entry.event === 'question.answered') return 'Response delivered';
  if (entry.event === 'question.dismissed') return 'Question dismissed';
  if (entry.event === 'question.delivery_failed')
    return 'Response delivery needs checking';
  if (entry.event === 'task.git_linked') return 'Git workspace linked';
  if (entry.event === 'task.git_unlinked') return 'Git workspace unlinked';
  if (entry.event === 'request.pending')
    return details.request_kind === 'question'
      ? 'Question requested'
      : details.request_kind === 'approval'
        ? 'Approval requested'
        : 'Response requested';
  if (entry.event === 'request.answered') return 'Sending response';
  if (entry.event === 'request.sent')
    return details.decision === 'decline'
      ? 'Decline response delivered'
      : details.decision === 'cancel'
        ? 'Cancel response delivered'
        : 'Response delivered';
  if (entry.event === 'turn/completed')
    return details.turn_status === 'failed'
      ? 'Execution failed'
      : details.turn_status === 'interrupted'
        ? 'Execution interrupted'
        : details.turn_status === 'completed'
          ? 'Execution completed'
          : 'Execution finished';
  if (entry.event === 'item/started' || entry.event === 'item/completed') {
    if (details.item_type === 'commandExecution')
      return entry.event === 'item/started'
        ? 'Command started'
        : 'Command finished';
    if (details.item_type === 'fileChange') return 'File changes recorded';
    if (details.item_type === 'agentMessage') return 'Final response recorded';
    if (details.item_type === 'plan') return 'Plan recorded';
    return entry.event === 'item/started'
      ? 'Work item started'
      : 'Work item completed';
  }
  const labels: Record<string, Copy> = {
    'task.created': 'Task created',
    'turn.submitting': 'Preparing execution',
    'turn.accepted': 'Execution started',
    'turn.failed': 'Execution failed',
    'turn/plan/updated': 'Progress updated',
    'turn.interrupt_requested': 'Interruption requested',
    'runtime.disconnected': 'Execution connection lost',
    'thread.recovered': 'Execution state recovered',
    'submission.recovered': 'Execution state recovered',
    'document.updated': 'Plan updated',
    'serverRequest/resolved': 'Request resolved',
    'task.environment.updated': 'Task environment updated',
    'task.environment.retry': 'Environment preparation retried',
    'thread.imported': 'Conversation imported',
    'thread.reconnected': 'Conversation reconnected',
    'agent.discovered': 'Agent joined the work',
    'agents.settled': 'Agent work finished',
    'agent.updated': 'Agent progress updated',
  };
  return labels[entry.event] ?? 'Work state updated';
}

function HistoryEntry({
  entry,
  task,
  t,
}: {
  entry: Entry;
  task: Detail;
  t: Translate;
}) {
  const data = entry.details ?? {};
  const failed =
    data.status === 'failed' ||
    ['errored', 'systemError'].includes(string(data.agent_status)) ||
    data.turn_status === 'failed' ||
    (typeof data.exit_code === 'number' && data.exit_code !== 0);
  const Icon = failed
    ? AlertTriangle
    : data.item_type === 'commandExecution'
      ? SquareTerminal
      : data.item_type === 'fileChange'
        ? FileCode2
        : entry.event.startsWith('request.')
          ? CircleHelp
          : entry.event === 'turn/plan/updated'
            ? ListTodo
            : entry.event === 'turn/completed'
              ? CheckCircle2
              : History;
  const steps = Array.isArray(data.steps) ? data.steps.map(record) : [];
  const files = Array.isArray(data.files)
    ? data.files.filter((value): value is string => typeof value === 'string')
    : [];
  const item = task.items.find(
    (row) => row.id === data.item_id && row.type === 'commandExecution',
  );
  return (
    <li className="history-entry" data-failed={failed}>
      <span className="history-entry-icon">
        <Icon size={16} aria-hidden="true" />
      </span>
      <article>
        <div className="history-entry-heading">
          <strong>{t(title(entry))}</strong>
          <time dateTime={entry.created_at}>
            {new Date(entry.created_at).toLocaleString(t.locale, {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
            })}
          </time>
        </div>
        {typeof data.agent_name === 'string' && data.agent_name && (
          <span className="history-detail">
            {data.agent_name} ·{' '}
            {t(
              ['completed', 'shutdown'].includes(string(data.agent_status))
                ? 'Completed'
                : data.agent_status === 'errored'
                  ? 'Execution failed'
                  : data.agent_status === 'interrupted'
                    ? 'Interrupted'
                    : ['active', 'running', 'pendingInit'].includes(
                          string(data.agent_status),
                        )
                      ? 'In progress'
                      : 'Unknown',
            )}
          </span>
        )}
        {typeof data.command === 'string' && data.command && (
          <code className="history-command">{data.command}</code>
        )}
        {typeof data.exit_code === 'number' && (
          <span className="history-detail">
            {t('Exit code')} {data.exit_code}
          </span>
        )}
        {typeof data.error_code === 'string' && data.error_code && (
          <p className="danger">{t(errorCopy(data.error_code))}</p>
        )}
        {steps.length > 0 && (
          <details className="history-entry-details">
            <summary>
              {t('Execution steps')} ·{' '}
              {steps.filter((row) => row.status === 'completed').length}/
              {steps.length}
            </summary>
            {typeof data.explanation === 'string' && data.explanation && (
              <p>{data.explanation}</p>
            )}
            <ol className="history-steps">
              {steps.map((row, index) => (
                <li key={index} data-state={string(row.status)}>
                  <span>{string(row.step)}</span>
                  <small>
                    {t(
                      row.status === 'completed'
                        ? 'Completed'
                        : row.status === 'inProgress'
                          ? 'In progress'
                          : 'Pending',
                    )}
                  </small>
                </li>
              ))}
            </ol>
          </details>
        )}
        {files.length > 0 && (
          <details className="history-entry-details">
            <summary>
              {t('Changed files')} · {files.length}
            </summary>
            <ul>
              {files.map((path, index) => (
                <li key={index}>
                  <code>{path}</code>
                </li>
              ))}
            </ul>
          </details>
        )}
        {item && (
          <details className="history-entry-details">
            <summary>{t('Command output')}</summary>
            <Command item={item} t={t} />
          </details>
        )}
        {data.truncated === true && (
          <p className="muted">{t('This history detail was shortened.')}</p>
        )}
      </article>
    </li>
  );
}

export function TaskHistory({ task, t }: { task: Detail; t: Translate }) {
  const [category, setCategory] = useState<Category>('all');
  const [snapshot, setSnapshot] = useState<(Page & { key: string }) | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [olderBusy, setOlderBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const key = `${task.id}:${category}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  const current = snapshot?.key === key ? snapshot : null;
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    void api<Page>(
      `/tasks/${task.id}/history?category=${category}`,
      undefined,
      'GET',
      controller.signal,
    )
      .then((value) => {
        if (controller.signal.aborted) return;
        setSnapshot((previous) => {
          if (previous?.key !== key) return { ...value, key };
          const merged = new Map(previous.items.map((row) => [row.id, row]));
          value.items.forEach((row) => merged.set(row.id, row));
          return {
            ...previous,
            items: [...merged.values()].sort((a, b) => b.id - a.id),
          };
        });
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(errorCopy(reason));
      });
    return () => controller.abort();
  }, [task.id, task.event_id, category, key, attempt]);
  return (
    <section className="task-history" aria-label={t('Task history')}>
      <header className="history-heading">
        <div>
          <h2>{t('Task history')}</h2>
          <p>
            {t(
              'Progress, responses and execution evidence remain available after a refresh.',
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('Refresh task history')}
          onClick={() => setAttempt((value) => value + 1)}
        >
          <History size={17} aria-hidden="true" />
        </Button>
      </header>
      <div
        className="history-filters"
        role="group"
        aria-label={t('Filter task history')}
      >
        {categories.map((item) => (
          <Button
            key={item.id}
            variant="ghost"
            aria-pressed={category === item.id}
            onClick={() => setCategory(item.id)}
          >
            {t(item.label)}
          </Button>
        ))}
      </div>
      {error && (
        <div role="alert" className="history-read-error">
          <p>{t(error as Copy)}</p>
          <Button onClick={() => setAttempt((value) => value + 1)}>
            {t('Retry')}
          </Button>
        </div>
      )}
      {!current && !error && <p role="status">{t('Loading task history…')}</p>}
      {current && current.items.length === 0 && (
        <p className="empty-result">
          {t('No activity recorded in this category yet.')}
        </p>
      )}
      {current && (
        <ol className="history-timeline">
          {current.items.map((entry) => (
            <HistoryEntry key={entry.id} entry={entry} task={task} t={t} />
          ))}
        </ol>
      )}
      {current?.items.some((entry) => !entry.details) && (
        <p className="history-legacy-note">
          {t(
            'Earlier activity includes its event and time; detailed snapshots were not recorded.',
          )}
        </p>
      )}
      {current?.next_before && (
        <Button
          disabled={olderBusy}
          onClick={() => {
            setOlderBusy(true);
            setError(null);
            void api<Page>(
              `/tasks/${task.id}/history?category=${category}&before=${current.next_before}`,
            )
              .then((value) =>
                setSnapshot((previous) => {
                  if (previous?.key !== key) return previous;
                  const merged = new Map(
                    previous.items.map((row) => [row.id, row]),
                  );
                  value.items.forEach((row) => merged.set(row.id, row));
                  return {
                    ...previous,
                    next_before: value.next_before,
                    items: [...merged.values()].sort((a, b) => b.id - a.id),
                  };
                }),
              )
              .catch((reason) => {
                if (currentKey.current === key) setError(errorCopy(reason));
              })
              .finally(() => setOlderBusy(false));
          }}
        >
          {t(olderBusy ? 'Loading earlier activity…' : 'Load earlier activity')}
        </Button>
      )}
    </section>
  );
}
