import type { ReactNode, Ref, UIEventHandler } from 'react';

/** Shared reading width and hierarchy for the console's browse/monitor pages. */
export function PageLayout({
  title,
  description,
  actions,
  navigation,
  className = '',
  scrollRef,
  onScroll,
  children,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  navigation?: ReactNode;
  className?: string;
  scrollRef?: Ref<HTMLElement>;
  onScroll?: UIEventHandler<HTMLElement>;
  children: ReactNode;
}) {
  return (
    <main
      className={`management-view ${className}`}
      ref={scrollRef}
      onScroll={onScroll}
    >
      <div className="page-content">
        <header className="page-heading">
          <div>
            <h1>{title}</h1>
            <p className="muted">{description}</p>
          </div>
          {actions && <div className="page-actions">{actions}</div>}
        </header>
        {navigation}
        {children}
      </div>
    </main>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-empty">
      <div className="page-empty-icon" aria-hidden="true">
        {icon}
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  );
}
