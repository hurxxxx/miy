import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

const CLOCKS = [
  { labelKey: 'planner.koreanTime', timeZone: 'Asia/Seoul' },
  { labelKey: 'planner.newYorkTime', timeZone: 'America/New_York' },
  { labelKey: 'planner.berlinTime', timeZone: 'Europe/Berlin' },
] as const;

export function WorldClocks() {
  const { i18n, t } = useTranslation('apps');
  const [now, setNow] = useState(() => new Date());
  const formatters = useMemo(
    () =>
      CLOCKS.map(({ labelKey, timeZone }) => ({
        labelKey,
        timeZone,
        date: new Intl.DateTimeFormat(i18n.language, {
          timeZone,
          year: 'numeric',
          month: 'short',
          day: 'numeric',
          weekday: 'short',
        }),
        time: new Intl.DateTimeFormat(i18n.language, {
          timeZone,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hourCycle: 'h23',
        }),
      })),
    [i18n.language],
  );

  useEffect(() => {
    const update = () => setNow(new Date());
    const updateWhenVisible = () => {
      if (!document.hidden) update();
    };
    const interval = window.setInterval(update, 1000);
    window.addEventListener('focus', update);
    document.addEventListener('visibilitychange', updateWhenVisible);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', update);
      document.removeEventListener('visibilitychange', updateWhenVisible);
    };
  }, []);

  return (
    <div
      role="group"
      aria-label={t('planner.currentTimes')}
      className="flex flex-wrap items-baseline gap-x-6 gap-y-2 border-b border-app-border pb-3"
    >
      {formatters.map(({ labelKey, timeZone, date, time }) => (
        <div
          key={timeZone}
          className="flex min-w-0 max-w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 text-app-ink"
        >
          <span className="app-text-overline text-app-ink-muted">
            {t(labelKey)}
          </span>
          <time
            dateTime={now.toISOString()}
            className="app-text-control tabular-nums"
          >
            {date.format(now)} {time.format(now)}
          </time>
        </div>
      ))}
    </div>
  );
}
