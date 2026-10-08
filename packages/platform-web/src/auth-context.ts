import i18n from 'i18next';
import { createContext, use } from 'react';

import type {
  AuthSessionItem,
  AuthSessionResponse,
  AuthUser,
  ChangePasswordPayload,
  DevLoginAccount,
  LoginPayload,
  SetupFirstUserPayload,
  SignupPayload,
  UpdatePreferencesPayload,
} from './auth-types.js';

export type AuthSessionStatus =
  | 'bootstrapping'
  | 'authenticated'
  | 'unauthenticated';

export interface AuthContextValue {
  status: AuthSessionStatus;
  user: AuthUser | null;
  token: string | null;
  /** Captured credential generation; does not grant server permissions. */
  isSessionCurrent?: () => boolean;
  requiresSetup: boolean;
  devAdminLoginAvailable: boolean;
  devLoginAccounts: DevLoginAccount[];
  bootstrapError: string | null;
  login: (payload: LoginPayload) => Promise<void>;
  signup: (payload: SignupPayload) => Promise<void>;
  loginAsDevelopmentAdmin: () => Promise<void>;
  loginAsDevelopmentAccount: (accountKey: string) => Promise<void>;
  setupFirstUser: (payload: SetupFirstUserPayload) => Promise<void>;
  switchSession: (session: AuthSessionResponse) => void;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  refreshAccessUser: () => Promise<AuthUser>;
  updatePreferences: (payload: UpdatePreferencesPayload) => Promise<void>;
  changePassword: (payload: ChangePasswordPayload) => Promise<void>;
  listSessions: () => Promise<AuthSessionItem[]>;
  revokeSession: (sessionId: string) => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const context = use(AuthContext);

  if (!context) {
    throw new Error(i18n.t('auth:errors.authProviderMissing'));
  }

  return context;
}
