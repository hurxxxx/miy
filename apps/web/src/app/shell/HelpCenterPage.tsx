import type { HelpGuide } from '@miy/core-web/help-guide';
import { ArrowLeft, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { NotFoundView } from '@/src/platform/auth/settings-pages';

import {
  getAiFeatureGuideSrc,
  getAiFeatureGuideTitleKey,
  hasAiFeatureGuide,
  type FeatureGuideToolIds,
} from './ai-feature-guides';

export type { HelpGuide } from '@miy/core-web/help-guide';

type HelpCenterPageProps = {
  guides?: readonly HelpGuide[];
  onOpenGuide?: (guide: HelpGuide) => void;
};

export function HelpCenterPage({
  guides = [],
  onOpenGuide,
}: HelpCenterPageProps = {}) {
  const { i18n, t } = useTranslation(['shell', 'common']);
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const [modalGuide, setModalGuide] = useState<HelpGuide | null>(null);
  const openGuide = onOpenGuide ?? ((guide: HelpGuide) => setModalGuide(guide));

  const renderCard = (guide: HelpGuide) => {
    const Icon = guide.icon;
    return (
      <button
        className="group rounded-lg border border-app-border bg-app-surface p-5 text-left shadow-sm transition-colors hover:border-app-accent/50 hover:bg-app-surface-hover"
        key={guide.key}
        onClick={() =>
          openGuide({ ...guide, src: guide.getSrc?.(locale) ?? guide.src })
        }
        type="button"
      >
        <span className="flex size-10 items-center justify-center rounded-lg border border-app-border bg-app-bg text-app-accent">
          <Icon size={20} />
        </span>
        <span className="mt-4 block text-base font-semibold text-app-ink">
          {t(guide.titleKey)}
        </span>
        <span className="app-text-body-sm mt-2 block text-app-ink/65">
          {t(guide.descriptionKey)}
        </span>
      </button>
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-10">
      <header className="max-w-3xl">
        <p className="app-text-overline text-app-accent">
          {t('helpCenter.eyebrow')}
        </p>
        <h1 className="mt-3 text-3xl font-semibold text-app-ink">
          {t('helpCenter.title')}
        </h1>
        <p className="app-text-body mt-3 text-app-ink/65">
          {t('helpCenter.description')}
        </p>
      </header>

      <section
        aria-label={t('helpCenter.sectionLabel')}
        className="flex flex-col gap-4"
      >
        <h2 className="app-text-overline text-app-ink/50">
          {t('helpCenter.sectionLabel')}
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {guides.map(renderCard)}
        </div>
      </section>

      {modalGuide ? (
        <HelpGuideModal
          closeLabel={t('common:actions.close')}
          onClose={() => setModalGuide(null)}
          src={modalGuide.getSrc?.(locale) ?? modalGuide.src}
          title={t(modalGuide.titleKey)}
        />
      ) : null}
    </div>
  );
}

export function HelpGuidePage({ guide }: { guide: HelpGuide }) {
  const { i18n, t } = useTranslation('shell');

  return (
    <div className="flex h-full min-h-screen">
      <HelpGuideFrame
        src={
          guide.getSrc?.(i18n.resolvedLanguage ?? i18n.language) ?? guide.src
        }
        title={t(guide.titleKey)}
      />
    </div>
  );
}

export function HelpAiGuidePage({
  featureGuideToolIds,
}: {
  featureGuideToolIds: FeatureGuideToolIds;
}) {
  const { t } = useTranslation('shell');
  const { feature = '' } = useParams();
  const hasGuide = hasAiFeatureGuide(feature, featureGuideToolIds);
  if (!hasGuide) {
    return <NotFoundView />;
  }
  const title = t(getAiFeatureGuideTitleKey(feature));

  return (
    <div className="flex h-full min-h-screen">
      <HelpGuideFrame src={getAiFeatureGuideSrc(feature)} title={title} />
    </div>
  );
}

export function HelpCenterModal({
  closeLabel,
  guides = [],
  onClose,
}: {
  closeLabel: string;
  guides?: readonly HelpGuide[];
  onClose: () => void;
}) {
  const { i18n, t } = useTranslation(['shell', 'common']);
  const [activeGuide, setActiveGuide] = useState<HelpGuide | null>(null);
  const title = activeGuide ? t(activeGuide.titleKey) : t('helpCenter.title');

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]">
      <button
        aria-hidden="true"
        aria-label={closeLabel}
        className="absolute inset-0 cursor-default"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        aria-labelledby="help-center-modal-title"
        aria-modal="true"
        className="relative z-10 flex h-[90vh] w-[90vw] min-w-0 flex-col overflow-hidden border border-app-border bg-app-bg shadow-2xl"
        role="dialog"
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-app-border bg-app-bg px-4">
          <div className="flex min-w-0 items-center gap-2">
            {activeGuide ? (
              <button
                aria-label={t('helpCenter.backToHelpCenter')}
                className="flex size-9 items-center justify-center rounded-lg text-app-ink/60 transition-colors hover:bg-app-surface-hover hover:text-app-ink"
                onClick={() => setActiveGuide(null)}
                title={t('helpCenter.backToHelpCenter')}
                type="button"
              >
                <ArrowLeft size={18} />
              </button>
            ) : null}
            <h2
              className="truncate text-base font-semibold text-app-ink"
              id="help-center-modal-title"
            >
              {title}
            </h2>
          </div>
          <button
            aria-label={closeLabel}
            className="flex size-9 items-center justify-center rounded-lg text-app-ink/60 transition-colors hover:bg-app-surface-hover hover:text-app-ink"
            onClick={onClose}
            title={closeLabel}
            type="button"
          >
            <X size={18} />
          </button>
        </header>

        {activeGuide ? (
          <HelpGuideFrame
            src={
              activeGuide.getSrc?.(i18n.resolvedLanguage ?? i18n.language) ??
              activeGuide.src
            }
            title={title}
          />
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <HelpCenterPage
              guides={guides}
              onOpenGuide={(guide) => setActiveGuide(guide)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function HelpGuideFrame({ src, title }: { src: string; title: string }) {
  return (
    <iframe
      className="min-h-0 flex-1 border-0 bg-white"
      src={src}
      title={title}
    />
  );
}

export function HelpGuideModal({
  closeLabel,
  onClose,
  src,
  title,
}: {
  closeLabel: string;
  onClose: () => void;
  src: string;
  title: string;
}) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 p-4 backdrop-blur-[2px]">
      <button
        aria-hidden="true"
        aria-label={closeLabel}
        className="absolute inset-0 cursor-default"
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        aria-labelledby="help-guide-modal-title"
        aria-modal="true"
        className="relative z-10 flex h-[90vh] w-[90vw] min-w-0 flex-col overflow-hidden border border-app-border bg-app-bg shadow-2xl"
        role="dialog"
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-app-border bg-app-bg px-4">
          <h2
            className="text-base font-semibold text-app-ink"
            id="help-guide-modal-title"
          >
            {title}
          </h2>
          <button
            aria-label={closeLabel}
            className="flex size-9 items-center justify-center rounded-lg text-app-ink/60 transition-colors hover:bg-app-surface-hover hover:text-app-ink"
            onClick={onClose}
            title={closeLabel}
            type="button"
          >
            <X size={18} />
          </button>
        </header>

        <HelpGuideFrame src={src} title={title} />
      </div>
    </div>
  );
}
