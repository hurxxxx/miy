import { Button, FeedbackProvider, useFeedback } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { active, type Detail } from './api';
import type { Translate } from './i18n';
import { RequestForm } from './views';

type Props = {
  task: Detail;
  t: Translate;
  busy: boolean;
  onAnswer: (id: string, response: unknown) => Promise<boolean>;
  onAsyncAnswer?: (id: string, response: unknown) => Promise<boolean>;
  onRefreshQuestions?: () => Promise<boolean>;
};

export function TaskDecisions(props: Props) {
  return (
    <FeedbackProvider
      labels={{
        close: props.t('Close notification'),
        item: props.t('Notification'),
        region: props.t('Task notifications'),
      }}
    >
      <DecisionRequests {...props} />
      <AsyncDecisions {...props} />
    </FeedbackProvider>
  );
}

function AsyncDecisions({
  task,
  t,
  busy,
  onAsyncAnswer,
  onRefreshQuestions,
}: Props) {
  const questions = task.async_questions ?? [];
  const [sending, setSending] = useState<string | null>(null);
  const inFlight = useRef(false);
  const feedback = useFeedback();
  const submit = async (id: string, body: unknown) => {
    if (!onAsyncAnswer || inFlight.current || busy) return;
    inFlight.current = true;
    setSending(id);
    try {
      const ok = await onAsyncAnswer(id, body);
      feedback.show({
        title: t(
          ok
            ? 'Response received. Following the next step.'
            : 'Response was not confirmed. Check the current request before retrying.',
        ),
        tone: ok ? 'success' : 'warning',
      });
    } catch {
      feedback.show({
        title: t(
          'Response was not confirmed. Check the current request before retrying.',
        ),
        tone: 'warning',
      });
    } finally {
      inFlight.current = false;
      setSending(null);
    }
  };
  const pending = questions.filter(
    (q) => !['answered', 'dismissed'].includes(q.state),
  );
  const history = questions.filter((q) =>
    ['answered', 'dismissed'].includes(q.state),
  );
  if (!questions.length && !task.thread_id) return null;
  return (
    <section
      className="async-decisions stack"
      aria-label={t('Async questions')}
    >
      {pending.length > 0 && (
        <h2>
          {t('Your response is needed')} · {pending.length}
        </h2>
      )}
      {pending.map((q) => (
        <div className="async-question" key={q.id}>
          {q.state === 'unconfirmed' && (
            <p className="context-note">
              {t(
                'Previous response unknown. You can answer again or dismiss this question.',
              )}
            </p>
          )}
          {['sending', 'uncertain'].includes(q.state) && (
            <p role="status">
              {t(
                'Response delivery is being checked. Recover execution before retrying.',
              )}
            </p>
          )}
          <RequestForm
            t={t}
            request={{
              id: q.id,
              method: 'item/tool/requestUserInput',
              payload: {
                questions: q.questions.map((question, i) => ({
                  id: String(i),
                  header: `${t('Question')} ${i + 1}`,
                  question: question.title,
                  options: (question.options ?? []).map((label) => ({ label })),
                })),
              },
            }}
            initialAnswers={Object.fromEntries(
              Object.entries(q.answers ?? {}).map(([id, values]) => [
                id,
                values[0] ?? '',
              ]),
            )}
            submitLabel={
              active(task) ? 'Submit answers' : 'Answer and continue'
            }
            disabled={
              busy ||
              !!sending ||
              ['starting', 'uncertain'].includes(task.status) ||
              ['sending', 'uncertain'].includes(q.state)
            }
            onAnswer={(id, response) => {
              void submit(id, response);
            }}
          />
          <Button
            variant="ghost"
            disabled={
              busy || !!sending || ['sending', 'uncertain'].includes(q.state)
            }
            onClick={() => {
              void submit(q.id, { action: 'dismiss' });
            }}
          >
            {t('Dismiss question')}
          </Button>
        </div>
      ))}
      {(history.length > 0 || onRefreshQuestions) && (
        <details className="question-history">
          <summary>{t('Question history')}</summary>
          {history.map((q) => (
            <article key={q.id}>
              <strong>
                {t(
                  q.state === 'answered'
                    ? 'Response delivered'
                    : 'Question dismissed',
                )}
              </strong>
              {q.questions.map((prompt, i) => (
                <div key={i}>
                  <p>{prompt.title}</p>
                  <p>{q.answers?.[String(i)]?.join('\n')}</p>
                </div>
              ))}
            </article>
          ))}
          {onRefreshQuestions && (
            <Button
              disabled={busy || !!sending}
              onClick={() => {
                void onRefreshQuestions();
              }}
            >
              {t('Restore questions from conversation')}
            </Button>
          )}
        </details>
      )}
    </section>
  );
}

function DecisionRequests({ task, t, busy, onAnswer }: Props) {
  const feedback = useFeedback();
  const [selected, setSelected] = useState<string | null>(null);
  const sending = useRef(false);
  const submitted = useRef<string | null>(null);
  const region = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const current =
    task.requests.find((row) => row.id === selected) ?? task.requests[0];
  const receipt = (accepted: boolean) =>
    feedback.show({
      title: t(
        accepted
          ? 'Response received. Following the next step.'
          : 'Response was not confirmed. Check the current request before retrying.',
      ),
      tone: accepted ? 'success' : 'warning',
      announcement: accepted ? 'polite' : 'assertive',
      dedupeKey: `response:${task.id}`,
      description: t('Confirmed activity remains available in task history.'),
    });
  useEffect(() => {
    if (
      !submitted.current ||
      task.requests.some((row) => row.id === submitted.current)
    )
      return;
    submitted.current = null;
    if (
      document.activeElement !== document.body &&
      !region.current?.contains(document.activeElement)
    )
      return;
    const next = current
      ? heading.current
      : region.current?.parentElement?.querySelector<HTMLTextAreaElement>(
          '.composer textarea',
        );
    next?.focus({ preventScroll: true });
  }, [task.requests, current]);
  return (
    <section
      ref={region}
      className="decision-area"
      aria-label={t('Your next decisions')}
    >
      {current && (
        <>
          <div className="work-section-heading">
            <h2 ref={heading} tabIndex={-1}>
              {t('Your response is needed')}
            </h2>
            <span>
              {task.requests.findIndex((row) => row.id === current.id) + 1} /{' '}
              {task.requests.length}
            </span>
          </div>
          {task.requests.length > 1 && (
            <div
              className="decision-switch"
              role="group"
              aria-label={t('Pending requests')}
            >
              {task.requests.map((row, index) => (
                <Button
                  key={row.id}
                  variant="ghost"
                  aria-pressed={row.id === current.id}
                  onClick={() => setSelected(row.id)}
                >
                  {t(
                    row.method === 'item/tool/requestUserInput'
                      ? 'Question'
                      : 'Approval',
                  )}{' '}
                  {index + 1}
                </Button>
              ))}
            </div>
          )}
          {task.requests.map((request) => (
            <div key={request.id} hidden={request.id !== current.id}>
              <RequestForm
                request={request}
                t={t}
                disabled={busy}
                onAnswer={(id, response) => {
                  if (sending.current || busy) return;
                  sending.current = true;
                  submitted.current = id;
                  void onAnswer(id, response)
                    .then(receipt)
                    .catch(() => receipt(false))
                    .finally(() => {
                      sending.current = false;
                    });
                }}
              />
            </div>
          ))}
        </>
      )}
    </section>
  );
}
