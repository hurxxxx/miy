import { active, record, string, type Task } from './api';
import type { components } from './api.generated';
import { type Copy, type Translate } from './i18n';
export type Agent = components['schemas']['AgentOut'];
export type NativeFreshness = NonNullable<Agent['observation']>['freshness'];

/** Observation metadata explains execution records; it never grants action eligibility. */
export function nativeThreadStatus(agent: Agent): Copy {
  return (
    (
      {
        active: 'Running',
        idle: 'Idle',
        notLoaded: 'Not loaded',
        systemError: 'Needs recovery',
      } as Record<string, Copy>
    )[agent.observation?.thread_status ?? ''] ?? 'Unknown'
  );
}

export function currentNativeStatus(
  agent: Agent,
  freshness = agent.observation?.freshness,
): Copy {
  return freshness === 'fresh' && agent.observation?.thread_status
    ? nativeThreadStatus(agent)
    : 'Current state unknown';
}

export function nativeObservationStatus(
  agent: Agent,
  freshness = agent.observation?.freshness,
): Copy {
  return (
    (
      {
        fresh: 'Recent native observation',
        stale: 'Stale observation',
        unavailable: 'Native observation unavailable',
        unknown: 'No native observation yet',
      } as Record<string, Copy>
    )[freshness ?? 'unknown'] ?? 'No native observation yet'
  );
}

export function observedTurnStatus(agent: Agent): Copy {
  return (
    (
      {
        inProgress: 'Running',
        completed: 'Completed',
        interrupted: 'Interrupted',
        failed: 'Failed',
      } as Record<string, Copy>
    )[agent.observation?.last_turn?.status ?? ''] ?? 'Unknown'
  );
}

export function observationFailure(agent: Agent): Copy | null {
  return (
    (
      {
        unavailable: 'Native connection unavailable',
        read_failed: 'Native state read failed',
        identity_mismatch: 'Native observation identity could not be verified',
      } as Record<string, Copy>
    )[agent.observation?.error_code ?? ''] ?? null
  );
}

const terminal = new Set(['completed', 'interrupted', 'errored', 'shutdown']);
export const agentWorking = (agent: Agent) =>
  ['active', 'running', 'pendingInit'].includes(agent.status);
export const agentWaiting = (agent: Agent) =>
  !terminal.has(agent.status) && !!agent.flags?.length;
export const agentAttention = (agent: Agent) =>
  agentWaiting(agent) ||
  ![
    'active',
    'running',
    'pendingInit',
    'idle',
    'notLoaded',
    'completed',
    'interrupted',
    'shutdown',
  ].includes(agent.status);
export const executing = (task: Task) =>
  ['starting', 'running', 'waiting'].includes(task.status) ||
  task.agents?.some(agentWorking);

export function needsAttention(task: Task) {
  return (
    planNeedsReview(task) ||
    !!task.pending_count ||
    ['waiting', 'failed', 'uncertain'].includes(task.status) ||
    task.agents?.some(agentAttention)
  );
}
export function running(task: Task) {
  // Conservative stop/recovery eligibility; use executing() for activity counts.
  return (
    ['starting', 'running', 'waiting'].includes(task.status) ||
    task.agents?.some((a) => a.parent_thread_id && !terminal.has(a.status))
  );
}
export function taskRank(task: Task) {
  return needsAttention(task)
    ? 0
    : executing(task)
      ? 1
      : !task.thread_id
        ? 2
        : 3;
}
export function sortTasks(tasks: Task[]) {
  return [...tasks].sort(
    (a, b) =>
      Number(!!b.pinned) - Number(!!a.pinned) ||
      taskRank(a) - taskRank(b) ||
      b.updated_at.localeCompare(a.updated_at) ||
      a.id.localeCompare(b.id),
  );
}

export function agentStatus(agent: Agent): Copy {
  if (agentWaiting(agent) && agent.flags?.includes('waitingOnApproval'))
    return 'Approval needed';
  if (agentWaiting(agent) && agent.flags?.includes('waitingOnUserInput'))
    return 'Waiting for your response';
  return (
    (
      {
        active: 'Running',
        running: 'Running',
        pendingInit: 'Starting',
        idle: 'Ready',
        notLoaded: 'Not loaded',
        completed: 'Completed',
        interrupted: 'Interrupted',
        errored: 'Failed',
        systemError: 'Needs recovery',
        shutdown: 'Stopped',
        notFound: 'Unknown',
      } as Record<string, Copy>
    )[agent.status] ?? 'Unknown'
  );
}
export function activity(value: string | null | undefined, t: Translate) {
  const labels: Record<string, Copy> = {
    command: 'Running a command',
    files: 'Editing files',
    search: 'Searching',
    delegating: 'Delegating work',
  };
  return value ? (labels[value] ? t(labels[value]) : value) : '';
}

export type Group = 'attention' | 'running' | 'waiting' | 'finished';

export function hasFinished(task: Task) {
  if (executing(task) || task.status === 'uncertain' || task.pending_count)
    return false;
  if (
    task.agents.some(
      (agent) => agent.parent_thread_id && !terminal.has(agent.status),
    )
  )
    return false;
  return (
    !!task.summary?.latest_result ||
    ['review', 'interrupted', 'failed'].includes(task.status) ||
    task.agents.some(
      (agent) => !agent.parent_thread_id && terminal.has(agent.status),
    )
  );
}

export function activityGroup(task: Task): Group | null {
  if (needsAttention(task)) return 'attention';
  if (executing(task)) return 'running';
  // An unloaded or idle child is not proof of completion (or of execution).
  if (
    task.agents.some(
      (agent) => agent.parent_thread_id && !terminal.has(agent.status),
    )
  )
    return 'waiting';
  if (
    ['review', 'interrupted'].includes(task.status) ||
    !!task.summary?.latest_result ||
    task.agents.some(
      (agent) => !agent.parent_thread_id && terminal.has(agent.status),
    )
  )
    return 'finished';
  return task.thread_id ? 'waiting' : null;
}

export function currentStep(task: Task, t: Translate) {
  const root = task.agents.find((agent) => !agent.parent_thread_id);
  const rootRunning = root ? agentWorking(root) : active(task);
  const currentAgent = rootRunning ? root : task.agents.find(agentWorking);
  const steps = rootRunning
    ? task.progress?.steps
    : currentAgent?.progress?.steps;
  const current = Array.isArray(steps)
    ? steps.map(record).find((step) => step.status === 'inProgress')
    : null;
  return (
    string(current?.step) ||
    activity(currentAgent?.activity, t) ||
    t('No current step reported')
  );
}

export function executionCount(task: Task) {
  const root = task.agents.find((agent) => !agent.parent_thread_id);
  return (
    Number(active(task) || (!!root && agentWorking(root))) +
    task.agents.filter((agent) => agent.parent_thread_id && agentWorking(agent))
      .length
  );
}

export function planNeedsReview(task: Task): boolean {
  const revisions =
    'revisions' in task && Array.isArray(task.revisions) ? task.revisions : [];
  const latest =
    task.summary?.latest_plan ??
    revisions.filter((r) => r.kind === 'plan').at(-1);
  return (
    task.stage === 'plan' &&
    task.status === 'idle' &&
    !executing(task) &&
    !!latest &&
    latest.id !== task.approved_revision
  );
}

/** Human-facing status, shared by lists, activity and the open workspace. */
export function taskStatus(task: Task): Copy {
  if (task.status === 'uncertain') return 'Current state unknown';
  const kinds = task.summary?.pending_kinds ?? [];
  const requests =
    'requests' in task && Array.isArray(task.requests) ? task.requests : [];
  if (task.pending_count || task.agents.some(agentWaiting) || requests.length) {
    if (
      kinds.includes('question') ||
      requests.some((r) => r.method === 'item/tool/requestUserInput') ||
      task.agents.some((a) => a.flags?.includes('waitingOnUserInput'))
    )
      return 'Waiting for your response';
    if (
      kinds.includes('approval') ||
      requests.some((r) => r.method.endsWith('requestApproval')) ||
      task.agents.some((a) => a.flags?.includes('waitingOnApproval'))
    )
      return 'Approval needed';
    return 'Needs attention';
  }
  if (
    task.status === 'failed' ||
    task.agents.some((agent) => agent.status === 'errored')
  )
    return 'Failed';
  if (task.agents.some(agentAttention)) return 'Current state unknown';
  if (task.status === 'interrupted') return 'Interrupted';
  if (executing(task))
    return task.status === 'starting' ? 'Starting' : 'Running';
  if (running(task)) return 'Awaiting confirmation';
  if (planNeedsReview(task)) return 'Plan review needed';
  if (hasFinished(task) || task.stage === 'review') return 'Result ready';
  if (!task.thread_id && task.status === 'idle') return 'Not started';
  return 'Awaiting confirmation';
}

export function taskAction(task: Task): Copy {
  if (task.pending_count) return 'Review request';
  if (planNeedsReview(task)) return 'Review plan';
  if (task.status === 'uncertain' || task.status === 'failed')
    return 'Check work state';
  if (executing(task)) return 'View work';
  return hasFinished(task) ? 'View result' : 'Continue development';
}

export function rowStatus(task: Task, _group: Group): Copy {
  return taskStatus(task);
}
