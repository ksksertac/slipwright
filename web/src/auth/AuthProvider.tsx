import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, useLocation } from "react-router-dom";
import { api, ApiError, UNAUTHORIZED_EVENT, type User } from "../api/client";
import { keys } from "../api/hooks";
import { currentLang, useT } from "../i18n";

interface AuthState {
  user: User | null;
  loading: boolean;
  /** 503 from the API: no user exists yet; the page shows how to create one. */
  noUsers: boolean;
  /** Signed in but the address is still unproved: the app is read-only until it is. */
  unverified: boolean;
  login: (username: string, password: string) => Promise<User>;
  signUp: (email: string, password: string, name: string) => Promise<User>;
  /** Redeem a link from a letter. `verify` proves the address; `reset` sets a password. */
  verifyEmail: (token: string) => Promise<User>;
  resetPassword: (token: string, password: string) => Promise<User>;
  /** Take an invitation onto an agent: the password is chosen here and now. */
  acceptInvitation: (token: string, password: string, name: string) => Promise<User>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return await api.get<User>("/api/auth/me");
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 503)) {
          return { status: error.status } as const;
        }
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    const onUnauthorized = () => {
      qc.setQueryData(keys.me, { status: 401 });
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc]);

  const login = useCallback(
    async (username: string, password: string) => {
      const user = await api.post<User>("/api/auth/login", { username, password });
      qc.setQueryData(keys.me, user);
      await qc.invalidateQueries();
      return user;
    },
    [qc],
  );

  // signup, verification and reset all end with a session, so they land the same way
  const arrive = useCallback(
    async (path: string, body: Record<string, unknown>) => {
      const user = await api.post<User>(path, { lang: currentLang(), ...body });
      qc.setQueryData(keys.me, user);
      await qc.invalidateQueries();
      return user;
    },
    [qc],
  );

  const signUp = useCallback(
    (email: string, password: string, name: string) =>
      arrive("/api/auth/signup", { email, password, name }),
    [arrive],
  );

  const verifyEmail = useCallback(
    (token: string) => arrive("/api/auth/verify", { token }),
    [arrive],
  );

  const resetPassword = useCallback(
    (token: string, password: string) => arrive("/api/auth/reset-password", { token, password }),
    [arrive],
  );

  const acceptInvitation = useCallback(
    (token: string, password: string, name: string) =>
      arrive("/api/auth/accept-invitation", { token, password, name }),
    [arrive],
  );

  const logout = useCallback(async () => {
    await api.post<void>("/api/auth/logout");
    qc.clear();
    qc.setQueryData(keys.me, { status: 401 });
  }, [qc]);

  const value = useMemo<AuthState>(() => {
    const data = me.data;
    const user = data && "username" in data ? data : null;
    return {
      user,
      loading: me.isLoading,
      noUsers: !!data && "status" in data && data.status === 503,
      // an account with no address at all predates signup: there is nothing to prove
      unverified: !!user && !!user.email && !user.email_verified_at,
      login,
      signUp,
      verifyEmail,
      resetPassword,
      acceptInvitation,
      logout,
    };
  }, [
    me.data,
    me.isLoading,
    login,
    signUp,
    verifyEmail,
    resetPassword,
    acceptInvitation,
    logout,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** Wraps routes that need a session; unauthenticated visits go to /login and back. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const tx = useT();
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="centered muted">{tx("Loading…")}</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}
