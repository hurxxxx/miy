import { expect, it } from 'vitest';
import { widgetSurfaceClip } from './OfficialWidgetFrame';
import { firstPartyUiOwner } from '../deployment/first-party-navigation';

it('clips to dock/panel geometry within the portal viewport and closes absent surfaces', () => {
  expect(widgetSurfaceClip([], 1000, 700)).toBe("path('M0,0H0V0Z')");
  expect(
    widgetSurfaceClip(
      [
        { left: 960, right: 1000, top: 0, bottom: 700 },
        { left: 100, right: 950, top: -20, bottom: 900 },
      ],
      1000,
      700,
    ),
  ).toBe("path('M960,0H1000V700H960Z M100,0H950V700H100Z')");
  expect(firstPartyUiOwner('/apps/docs/documents/item')).toBe('official');
  expect(firstPartyUiOwner('/apps/docs-other')).toBe('platform');
  expect(firstPartyUiOwner('/official-suite/widgets')).toBe('official');
  expect(firstPartyUiOwner('/apps/home')).toBe('platform');
});
