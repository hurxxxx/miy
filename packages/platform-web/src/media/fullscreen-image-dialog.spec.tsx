// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FullscreenImageDialog } from './fullscreen-image-dialog';
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(() => cleanup());
it('keeps accessible image controls and releases scroll/Escape ownership on unmount', () => {
  const close = vi.fn();
  document.body.style.overflow = 'auto';
  const r = render(
    <FullscreenImageDialog
      src="blob:synthetic"
      alt="Preview"
      title="image.png"
      onClose={close}
    />,
  );
  expect(screen.getByRole('dialog', { name: 'image.png' })).toBeTruthy();
  expect(screen.getByRole('img', { name: 'Preview' }).getAttribute('src')).toBe(
    'blob:synthetic',
  );
  expect(document.body.style.overflow).toBe('hidden');
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'actions.close' }));
  expect(close).toHaveBeenCalledTimes(2);
  r.unmount();
  expect(document.body.style.overflow).toBe('auto');
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(2);
  document.body.style.overflow = '';
});
