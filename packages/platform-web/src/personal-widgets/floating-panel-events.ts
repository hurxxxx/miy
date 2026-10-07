export const FLOATING_DM_OPEN_EVENT = 'miy:floating-dm-open';
export const FLOATING_PMS_OPEN_EVENT = 'miy:floating-pms-open';
export const PERSONAL_TODO_PMS_TASK_CREATED_EVENT =
  'miy:personal-todo-pms-task-created';

export type FloatingDmOpenEventDetail = {
  threadId?: string | null;
};

export type FloatingPmsOpenEventDetail =
  | { mode?: 'panel' }
  | {
      mode: 'createTask';
      preserveActivePanel?: boolean;
      sourceTodoId?: string | null;
      title?: string | null;
    }
  | {
      mode: 'openTask';
      taskId: string;
      taskListId?: string | null;
    };

export type PersonalTodoPmsTaskCreatedEventDetail = {
  taskId?: string | null;
  title?: string | null;
  todoId?: string | null;
};

export function dispatchFloatingPmsOpen(
  detail: FloatingPmsOpenEventDetail = { mode: 'panel' },
): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<FloatingPmsOpenEventDetail>(FLOATING_PMS_OPEN_EVENT, {
      detail,
    }),
  );
}
