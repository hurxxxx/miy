import type { Translate } from './i18n';

export function WorkspaceDivider({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (value: number) => void;
  t: Translate;
}) {
  const clamp = (n: number) => Math.max(30, Math.min(60, n));
  return (
    <div
      className="workspace-divider"
      role="separator"
      tabIndex={0}
      aria-label={t('Resize conversation and results')}
      aria-orientation="vertical"
      aria-valuemin={30}
      aria-valuemax={60}
      aria-valuenow={value}
      onKeyDown={(event) => {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          event.preventDefault();
          onChange(
            clamp(
              event.key === 'Home'
                ? 30
                : event.key === 'End'
                  ? 60
                  : value + (event.key === 'ArrowLeft' ? -5 : 5),
            ),
          );
        }
      }}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        event.currentTarget.focus();
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const parent =
          event.currentTarget.parentElement?.getBoundingClientRect();
        if (parent)
          onChange(
            Math.round(
              clamp(((event.clientX - parent.left) / parent.width) * 100),
            ),
          );
      }}
      onPointerUp={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId))
          event.currentTarget.releasePointerCapture(event.pointerId);
      }}
    />
  );
}
