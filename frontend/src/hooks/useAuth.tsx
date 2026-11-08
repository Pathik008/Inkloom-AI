import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { AuthTokenResponse, CurrentUser, RoleName, UserMembershipContext } from '../types';
import {
  ApiError,
  fetchCurrentUser,
  getStoredOrganisationId,
  getStoredToken,
  loginAccount,
  logoutAccount,
  registerAccount,
  setStoredOrganisationId,
  setStoredToken,
} from '../services/api';

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  sessionError: string | null;
  activeMembership: UserMembershipContext | null;
  activeOrganisationId: string | null;
  activeRole: RoleName | null;
  activePermissions: string[];
  hasPermission: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    full_name: string;
    email: string;
    password: string;
    confirm_password: string;
    organisation_name: string;
    organisation_description?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  switchOrganisation: (organisationId: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  applyAuthSession: (authResponse: AuthTokenResponse) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const applyAuthSession = useCallback((authResponse: AuthTokenResponse) => {
    setStoredToken(authResponse.access_token);
    const defaultOrgId =
      authResponse.user.active_organisation_id ??
      authResponse.user.memberships[0]?.organisation.id ??
      null;
    setStoredOrganisationId(defaultOrgId);
    setUser(authResponse.user);
    setSessionError(null);
  }, []);

  const refreshUser = useCallback(async (overrideOrgId?: string | null) => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }

    try {
      const targetOrg = overrideOrgId !== undefined ? overrideOrgId : getStoredOrganisationId();
      const me = await fetchCurrentUser(targetOrg);
      const resolvedOrg =
        me.active_organisation_id ?? me.memberships[0]?.organisation.id ?? null;
      setStoredOrganisationId(resolvedOrg);
      setUser(me);
      setSessionError(null);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        // If only the stored organisation header was invalid, retry without org header
        if (err.status === 403 && getStoredOrganisationId()) {
          setStoredOrganisationId(null);
          try {
            const fallbackMe = await fetchCurrentUser(null);
            setStoredOrganisationId(fallbackMe.active_organisation_id);
            setUser(fallbackMe);
            return;
          } catch {
            // Fall through to clear session
          }
        }
        setStoredToken(null);
        setStoredOrganisationId(null);
        setUser(null);
        setSessionError(err.message);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await loginAccount({ email, password });
      applyAuthSession(res);
    },
    [applyAuthSession],
  );

  const register = useCallback(
    async (payload: {
      full_name: string;
      email: string;
      password: string;
      confirm_password: string;
      organisation_name: string;
      organisation_description?: string;
    }) => {
      const res = await registerAccount(payload);
      applyAuthSession(res);
    },
    [applyAuthSession],
  );

  const logout = useCallback(async () => {
    try {
      if (getStoredToken()) {
        await logoutAccount();
      }
    } catch {
      // Clear local session state even if network or token already expired
    } finally {
      setStoredToken(null);
      setStoredOrganisationId(null);
      setUser(null);
    }
  }, []);

  const switchOrganisation = useCallback(
    async (organisationId: string) => {
      setStoredOrganisationId(organisationId);
      await refreshUser(organisationId);
    },
    [refreshUser],
  );

  const activeMembership = useMemo<UserMembershipContext | null>(() => {
    if (!user || user.memberships.length === 0) return null;
    return (
      user.memberships.find((m) => m.organisation.id === user.active_organisation_id) ??
      user.memberships[0]
    );
  }, [user]);

  const activeOrganisationId = activeMembership?.organisation.id ?? user?.active_organisation_id ?? null;
  const activeRole = activeMembership?.role ?? user?.active_role ?? null;
  const activePermissions = useMemo(
    () => activeMembership?.permissions ?? user?.active_permissions ?? [],
    [activeMembership, user],
  );

  const hasPermission = useCallback(
    (permission: string) => activePermissions.includes(permission),
    [activePermissions],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      sessionError,
      activeMembership,
      activeOrganisationId,
      activeRole,
      activePermissions,
      hasPermission,
      login,
      register,
      logout,
      switchOrganisation,
      refreshUser: () => refreshUser(),
      applyAuthSession,
    }),
    [
      user,
      loading,
      sessionError,
      activeMembership,
      activeOrganisationId,
      activeRole,
      activePermissions,
      hasPermission,
      login,
      register,
      logout,
      switchOrganisation,
      refreshUser,
      applyAuthSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return ctx;
}
