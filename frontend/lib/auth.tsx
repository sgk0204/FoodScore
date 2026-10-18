"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, onAccessTokenChange, refreshAccessToken } from "./api/client";
import type { User } from "./api/schemas";

type AuthState = {
  user: User | null;
  ready: boolean; // the silent refresh on page load has finished
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  deleteAccount: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const loadUser = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    // The access token is memory-only, so a reload starts signed-out; the httpOnly refresh
    // cookie (if any) silently restores the session.
    let cancelled = false;
    void (async () => {
      if (await refreshAccessToken()) await loadUser();
      if (!cancelled) setReady(true);
    })();
    const unsubscribe = onAccessTokenChange((token) => {
      if (token === null) setUser(null);
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [loadUser]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      login: async (email, password) => {
        await api.login(email, password);
        await loadUser();
      },
      register: async (email, password) => {
        await api.register(email, password);
        await loadUser();
      },
      logout: async () => {
        await api.logout();
        setUser(null);
      },
      deleteAccount: async () => {
        await api.deleteAccount();
        setUser(null);
      },
    }),
    [user, ready, loadUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
