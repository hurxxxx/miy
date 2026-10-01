import { active, record, string, type Task } from './api';
import type { components } from './api.generated';
import { statusCopy, type Copy, type Translate } from './i18n';
export type Agent = components['schemas']['AgentOut'];

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

export function rowStatus(task: Task, group: Group): Copy {
  if (task.pending_count || task.agents.some(agentWaiting))
    return 'Waiting for your response';
  if (group === 'attention')
    return needsAttention(task) &&
      !['failed', 'uncertain', 'waiting'].includes(task.status)
      ? 'Needs attention'
      : statusCopy(task.status);
  if (group === 'running')
    return task.status === 'starting' ? 'Starting' : 'Running';
  if (group === 'waiting') return 'Awaiting confirmation';
  if (task.status === 'interrupted') return 'Interrupted';
  if (task.status === 'review') return 'Result ready';
  const root = task.agents.find((agent) => !agent.parent_thread_id);
  return root ? agentStatus(root) : 'Completed';
}
