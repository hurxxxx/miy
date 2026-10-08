import { Button, Dialog } from '@miy/ui';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { useIndependentAppFiles } from './use-independent-app-files';

type Picker = ReturnType<typeof useIndependentAppFiles>;

export function IndependentFilePicker({
  picker,
  appName,
}: {
  picker: Picker;
  appName: string;
}) {
  const { t } = useTranslation('shell');
  const [query, setQuery] = useState('');
  const copy = (key: string) => t(`independentApps.files.${key}`);
  const view = picker.view;
  if (!view) return null;
  const ready = view.phase === 'ready';
  return (
    <Dialog
      open
      title={copy('title')}
      description={t('independentApps.files.description', { app: appName })}
      closeLabel={copy('cancel')}
      onOpenChange={(open) => {
        if (!open) picker.cancel();
      }}
      maxWidth="max-w-xl"
      actions={
        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="secondary" onClick={picker.cancel}>
            {copy('cancel')}
          </Button>
          <Button
            disabled={!ready || !view.selected}
            onClick={() => void picker.confirm()}
          >
            {copy(view.phase === 'confirming' ? 'confirming' : 'confirm')}
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-app-ink">
        <p className="app-text-body text-app-ink/70">{copy('limit')}</p>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            picker.search(query);
          }}
        >
          <label className="min-w-0 flex-1 space-y-1">
            <span className="app-text-control-sm">{copy('searchLabel')}</span>
            <input
              className="w-full rounded-md border border-app-border bg-app-surface px-3 py-2 text-app-ink"
              value={query}
              maxLength={120}
              disabled={!ready}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <Button type="submit" variant="secondary" disabled={!ready}>
            {copy('search')}
          </Button>
        </form>
        {view.error && (
          <p role="alert" className="app-text-body text-app-danger">
            {copy(view.error)}
          </p>
        )}
        {view.phase === 'loading' && <p role="status">{copy('loading')}</p>}
        {ready && view.incomplete && (
          <p role="status" className="app-text-body text-app-ink/70">
            {copy('incomplete')}
          </p>
        )}
        {ready && !view.error && view.items.length === 0 && (
          <p>
            {copy(
              view.next_cursor || view.incomplete ? 'noPageItems' : 'empty',
            )}
          </p>
        )}
        <fieldset
          disabled={!ready}
          className="max-h-64 space-y-2 overflow-auto"
        >
          <legend className="sr-only">{copy('files')}</legend>
          {view.items.map((file) => (
            <label
              key={file.file_id}
              className="flex cursor-pointer items-start gap-3 rounded-md border border-app-border p-3"
            >
              <input
                className="mt-1"
                type="radio"
                name={`selected-file-${view.requestId}`}
                checked={view.selected?.file_id === file.file_id}
                onChange={() => picker.choose(file)}
              />
              <span className="min-w-0 flex-1">
                <span className="block break-all app-text-body">
                  {file.name}
                </span>
                <span className="app-text-caption text-app-ink/60">
                  {t('independentApps.files.fileSize', {
                    size: file.size_bytes,
                  })}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
        {view.next_cursor && (
          <Button variant="secondary" disabled={!ready} onClick={picker.next}>
            {copy('next')}
          </Button>
        )}
        {view.selected && (
          <p className="app-text-body break-all">
            {t('independentApps.files.selected', { name: view.selected.name })}
          </p>
        )}
        <p className="app-text-caption text-app-ink/60">{copy('retention')}</p>
      </div>
    </Dialog>
  );
}
