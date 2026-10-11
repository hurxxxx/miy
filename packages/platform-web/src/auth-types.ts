import type { ApiSchema } from '@miy/contracts/api';
import type { ShellAppId } from '@miy/core-web/navigation-types';

export type ThemePreference = 'system' | 'light' | 'dark';
export type LocalePreference = 'ko-KR' | 'en-US';
export type DateFormatPreference =
  | 'korean'
  | 'iso'
  | 'us'
  | 'european'
  | 'locale';
export type AppBarAppId = ShellAppId;

export interface AppBarLayoutPreference {
  pinned_app_ids: AppBarAppId[];
}

export type AuthUser = Omit<
  ApiSchema<'AuthUserResponse'>,
  | 'created_at'
  | 'last_login_at'
  | 'login_blocked'
  | 'theme_preference'
  | 'locale'
  | 'time_zone'
  | 'date_format'
> & {
  app_bar_layout?: AppBarLayoutPreference | null;
  login_blocked?: boolean;
  theme_preference: ThemePreference;
  locale: LocalePreference;
  time_zone: string;
  date_format: DateFormatPreference;
  last_login_at?: string | null;
  created_at?: string;
};

export type BootstrapStatusResponse = ApiSchema<'BootstrapStatusResponse'>;

export type DevLoginAccount = ApiSchema<'DevLoginAccountResponse'>;

export type AuthSessionResponse = Omit<
  ApiSchema<'AuthSessionResponse'>,
  'user'
> & {
  user: AuthUser;
};

export type LoginPayload = ApiSchema<'LoginRequest'>;

export type SetupFirstUserPayload = ApiSchema<'SetupFirstUserRequest'>;

export type SignupPayload = ApiSchema<'SignupRequest'>;

export type UpdatePreferencesPayload = Omit<
  ApiSchema<'UpdatePreferencesRequest'>,
  'theme_preference' | 'locale' | 'time_zone' | 'date_format'
> & {
  app_bar_layout?: AppBarLayoutPreference | null;
  theme_preference?: ThemePreference;
  locale?: LocalePreference;
  time_zone?: string;
  date_format?: DateFormatPreference;
};

export type ChangePasswordPayload = ApiSchema<'ChangePasswordRequest'>;

export type AuthSessionItem = ApiSchema<'SessionListItemResponse'>;

export type AuthSessionsResponse = ApiSchema<'SessionListResponse'>;

export interface DesktopSessionLinkResponse {
  code: string;
  expires_at: string;
}
