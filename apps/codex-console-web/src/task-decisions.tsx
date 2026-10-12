import { Button } from '@miy/ui';
import { useEffect, useRef, useState } from 'react';
import { type Detail } from './api';
import type { Translate } from './i18n';
import { RequestForm } from './views';

export function TaskDecisions({
  task,
  t,
  busy,
  onAnswer,
}: {
  task: Detail;
  t: Translate;
  busy: boolean;
  onAnswer: (id: string, response: unknown) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<'sent' | 'failed' | null>(null);
  const sending = useRef(false);
  const submitted = useRef<string | null>(null);
  const region = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const current =
    task.requests.find((row) => row.id === selected) ?? task.requests[0];
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
      <p role="status" className="decision-receipt">
        {notice &&
          t(
            notice === 'sent'
              ? 'Response received. Following the next step.'
              : 'Response was not confirmed. Check the current request before retrying.',
          )}
      </p>
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
                  setNotice(null);
                  void onAnswer(id, response)
                    .then((accepted) => setNotice(accepted ? 'sent' : 'failed'))
                    .catch(() => setNotice('failed'))
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
