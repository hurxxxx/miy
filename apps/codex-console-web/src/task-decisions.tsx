import { Button, FeedbackProvider, useFeedback } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { type Detail } from './api';
import type { Translate } from './i18n';
import { RequestForm } from './views';

type Props = {
  task: Detail;
  t: Translate;
  busy: boolean;
  onAnswer: (id: string, response: unknown) => Promise<boolean>;
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
    </FeedbackProvider>
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
