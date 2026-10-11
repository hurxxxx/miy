import type { ApiSchema } from '@miy/contracts/api';

export type BootstrapNavItem = ApiSchema<'BootstrapNavItemResponse'>;
export type BootstrapApp = ApiSchema<'BootstrapAppResponse'>;
export type BootstrapAppBarCategoryItem =
  ApiSchema<'BootstrapAppBarCategoryItemResponse'>;
export type BootstrapAppBarCategory =
  ApiSchema<'BootstrapAppBarCategoryResponse'> & {
    pinnable?: boolean;
    contextLabel?: string;
  };
export type BootstrapKeywordSearchEntityType =
  ApiSchema<'BootstrapKeywordSearchEntityTypeResponse'>;
export type BootstrapKeywordSearch =
  ApiSchema<'BootstrapKeywordSearchResponse'>;
export type AppsBootstrapResponse = Omit<
  ApiSchema<'AppsBootstrapResponse'>,
  'app_bar_categories'
> & {
  app_bar_categories: BootstrapAppBarCategory[];
};
export type AppsBootstrapApp = AppsBootstrapResponse['apps'][number];
