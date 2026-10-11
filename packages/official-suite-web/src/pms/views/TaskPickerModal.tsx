import { useAppAdmission } from '@miy/platform-web/apps';
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { NoAccessNotice } from '@miy/platform-web/apps';
import { ResourcePickerDialog } from '@miy/platform-web/pickers';
import { useAuth } from '@miy/platform-web/auth-context';
import {
  listPmsTaskLists,
  listTaskListTasks,
  type PmsTask,
} from '../api/pms-api';
import {
  EMPTY_EXCLUDED_TASK_IDS,
  INITIAL_TASK_PICKER_MODAL_STATE,
  buildTaskPickerTaskParams,
  getVisibleTaskPickerTasks,
  taskPickerModalReducer,
} from './task-picker-model';

export interface TaskPickerModalCopy {
  titleKey: string;
  descriptionKey: string;
  appLabelKey: string;
  noAccessActionKey: string;
  loadListsErrorKey: string;
  loadTasksErrorKey: string;
  attachErrorKey: string;
  taskListLabelKey: string;
  noTaskListsKey: string;
  searchPlaceholderKey: string;
  emptyKey: string;
}

export interface TaskPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPick: (task: PmsTask) => Promise<void> | void;
  excludeTaskIds?: string[];

  copy?: TaskPickerModalCopy;
  contentClassName?: string;
  fixedTaskListId?: string | null;
  layer?: 'default' | 'elevated';
  overlayClassName?: string;
}

const DEFAULT_TASK_PICKER_MODAL_COPY: TaskPickerModalCopy = {
  titleKey: 'pms.taskPicker.title',
  descriptionKey: 'pms.taskPicker.description',
  appLabelKey: 'pms.taskPicker.pmsApp',
  noAccessActionKey: 'pms.taskPicker.attachAction',
  loadListsErrorKey: 'pms.taskPicker.errors.loadListsFailed',
  loadTasksErrorKey: 'pms.taskPicker.errors.loadTasksFailed',
  attachErrorKey: 'pms.taskPicker.errors.attachFailed',
  taskListLabelKey: 'pms.taskPicker.taskListLabel',
  noTaskListsKey: 'pms.taskPicker.noTaskLists',
  searchPlaceholderKey: 'pms.taskPicker.searchPlaceholder',
  emptyKey: 'pms.taskPicker.empty',
};

export function TaskPickerModal(props: TaskPickerModalProps) {
  const { token, user } = useAuth();
  const admitted = useAppAdmission('pms');
  const scope = useRef({
    token,
    userId: user?.id,
    open: props.isOpen,
    admitted,
    list: props.fixedTaskListId,
    epoch: 0,
  });
  if (
    scope.current.token !== token ||
    scope.current.userId !== user?.id ||
    scope.current.open !== props.isOpen ||
    scope.current.admitted !== admitted ||
    scope.current.list !== props.fixedTaskListId
  ) {
    scope.current = {
      token,
      userId: user?.id,
      open: props.isOpen,
      admitted,
      list: props.fixedTaskListId,
      epoch: scope.current.epoch + 1,
    };
  }
  const epoch = scope.current.epoch;
  return props.isOpen ? (
    <TaskPickerSession
      key={epoch}
      {...props}
      canAccess={Boolean(token) && admitted}
      isCurrent={() => scope.current.epoch === epoch}
    />
  ) : null;
}

function TaskPickerSession({
  isOpen,
  onClose,
  onPick,
  excludeTaskIds = EMPTY_EXCLUDED_TASK_IDS,
  copy = DEFAULT_TASK_PICKER_MODAL_COPY,
  contentClassName,
  fixedTaskListId = null,
  layer,
  overlayClassName,
  canAccess,
  isCurrent,
}: TaskPickerModalProps & { canAccess: boolean; isCurrent: () => boolean }) {
  const { t } = useTranslation('apps');
  const { token } = useAuth();
  const active = useRef(false);
  const closed = useRef(false);
  const pickOperation = useRef(0);
  const picking = useRef(false);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const {
    attachErrorKey,
    descriptionKey,
    emptyKey,
    loadListsErrorKey,
    loadTasksErrorKey,
    noAccessActionKey,
    noTaskListsKey,
    searchPlaceholderKey,
    taskListLabelKey,
    titleKey,
    appLabelKey,
  } = copy;
  const [
    {
      taskLists,
      selectedTaskListId,
      tasks,
      query,
      loading,
      submittingId,
      error,
    },
    dispatch,
  ] = useReducer(taskPickerModalReducer, INITIAL_TASK_PICKER_MODAL_STATE);
  const selection = useRef({ list: selectedTaskListId });
  if (selection.current.list !== selectedTaskListId) {
    selection.current = { list: selectedTaskListId };
  }
  const currentSelection = selection.current;
  const current = () =>
    active.current &&
    !closed.current &&
    isCurrent() &&
    selection.current === currentSelection;

  useEffect(() => {
    if (!isOpen || !token || !canAccess) return;
    let cancelled = false;
    dispatch({ type: 'resetForOpen', selectedTaskListId: fixedTaskListId });
    if (fixedTaskListId) {
      return () => {
        cancelled = true;
      };
    }
    listPmsTaskLists(token, undefined)
      .then((response) => {
        if (cancelled) return;
        dispatch({ type: 'taskListsLoaded', taskLists: response.items });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        dispatch({
          type: 'taskListsFailed',
          message: err.message || t(loadListsErrorKey),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [canAccess, fixedTaskListId, isOpen, loadListsErrorKey, t, token]);

  useEffect(() => {
    if (!isOpen || !token || !canAccess || !selectedTaskListId) {
      dispatch({ type: 'tasksIdle' });
      return;
    }
    let cancelled = false;
    dispatch({ type: 'tasksLoading' });
    listTaskListTasks(
      token,
      selectedTaskListId,
      buildTaskPickerTaskParams(query),
    )
      .then((response) => {
        if (cancelled) return;
        dispatch({ type: 'tasksLoaded', tasks: response.items });
      })
      .catch((err: Error) => {
        if (cancelled) return;
        dispatch({
          type: 'tasksFailed',
          message: err.message || t(loadTasksErrorKey),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [
    canAccess,
    isOpen,
    loadTasksErrorKey,
    query,
    selectedTaskListId,
    t,
    token,
  ]);

  const filteredTasks = useMemo(
    () => getVisibleTaskPickerTasks(tasks, excludeTaskIds),
    [excludeTaskIds, tasks],
  );

  async function handlePick(task: PmsTask) {
    if (!current() || !canAccess || picking.current) return;
    picking.current = true;
    const operation = ++pickOperation.current;
    const currentPick = () => current() && pickOperation.current === operation;
    dispatch({ type: 'pickStarted', taskId: task.id });
    try {
      await onPick(task);
      if (currentPick()) {
        closed.current = true;
        onClose();
      }
    } catch (err) {
      if (!currentPick()) return;
      dispatch({
        type: 'pickFailed',
        message: err instanceof Error ? err.message : t(attachErrorKey),
      });
    } finally {
      if (pickOperation.current === operation) picking.current = false;
      if (currentPick()) dispatch({ type: 'pickFinished' });
    }
  }

  return (
    <ResourcePickerDialog
      accessNotice={
        <NoAccessNotice
          appLabel={t(appLabelKey)}
          action={t(noAccessActionKey)}
        />
      }
      canAccess={canAccess}
      closeLabel={t('common:actions.close')}
      contentClassName={contentClassName}
      controlsSlot={
        fixedTaskListId ? null : (
          <label className="block space-y-1">
            <span className="app-text-control-sm text-app-ink/70">
              {t(taskListLabelKey)}
            </span>
            <select
              value={selectedTaskListId ?? ''}
              onChange={(event) => {
                pickOperation.current += 1;
                picking.current = false;
                selection.current = { list: event.target.value || null };
                dispatch({
                  type: 'setSelectedTaskListId',
                  taskListId: event.target.value || null,
                });
              }}
              className="app-field-input"
            >
              {taskLists.length === 0 ? (
                <option value="">{t(noTaskListsKey)}</option>
              ) : null}
              {taskLists.map((taskList) => (
                <option key={taskList.id} value={taskList.id}>
                  {taskList.key} · {taskList.name}
                </option>
              ))}
            </select>
          </label>
        )
      }
      description={t(descriptionKey)}
      emptyLabel={t(emptyKey)}
      error={error}
      getItemId={(task) => task.id}
      isOpen={isOpen}
      items={filteredTasks}
      layer={layer}
      loading={loading}
      overlayClassName={overlayClassName}
      onClose={() => {
        if (!current()) return;
        closed.current = true;
        pickOperation.current += 1;
        picking.current = false;
        onClose();
      }}
      onPick={(task) => void handlePick(task)}
      renderItem={(task) => (
        <div className="min-w-0">
          <p className="app-text-body line-clamp-1 text-app-ink">
            {task.title}
          </p>
          <p className="app-text-caption text-app-ink/40">
            {task.reference} · {task.status_label}
          </p>
        </div>
      )}
      search={{
        label: t('common:actions.search'),
        onChange: (value) => dispatch({ type: 'setQuery', query: value }),
        placeholder: t(searchPlaceholderKey),
        value: query,
      }}
      submittingId={submittingId}
      title={t(titleKey)}
    />
  );
}
