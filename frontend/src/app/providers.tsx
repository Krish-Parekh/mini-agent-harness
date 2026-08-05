"use client";

import type { Session } from "@supabase/supabase-js";
import { QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";

import { TooltipProvider } from "@/components/ui/tooltip";
import { api, type AuthState } from "@/lib/api";
import { FilterProvider } from "@/lib/filters";
import { queryClient } from "@/lib/query-client";
import { signInWithGitHub, supabase, supabaseConfigured } from "@/lib/supabase";

type AuthContextValue = {
  loading: boolean;
  session: Session | null;
  auth: AuthState | null;
  configured: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  disconnectGitHub: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <Providers>");
  return value;
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(supabaseConfigured);

  const refresh = useCallback(async () => {
    setAuth(await api.me());
  }, []);

  useEffect(() => {
    if (!supabaseConfigured) return;

    let active = true;

    async function sync(next: Session | null) {
      if (!active) return;
      setSession(next);
      if (!next) {
        setAuth(null);
        setLoading(false);
        return;
      }
      try {
        setAuth(await api.syncAuth(next.provider_token));
      } catch {
        setAuth(null);
      } finally {
        if (active) setLoading(false);
      }
    }

    supabase.auth.getSession().then(({ data }) => sync(data.session));

    const { data: subscription } = supabase.auth.onAuthStateChange(
      (event, next) => {
        if (event === "TOKEN_REFRESHED") {
          setSession(next);
          return;
        }
        void sync(next);
      },
    );

    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async () => {
    await signInWithGitHub();
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
    setAuth(null);
  }, []);

  const disconnectGitHub = useCallback(async () => {
    await api.disconnectGitHub();
    await refresh();
  }, [refresh]);

  return (
    <AuthContext
      value={{
        loading,
        session,
        auth,
        configured: supabaseConfigured,
        signIn,
        signOut,
        disconnectGitHub,
        refresh,
      }}
    >
      {children}
    </AuthContext>
  );
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { loading, auth } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !auth) router.replace("/");
  }, [loading, auth, router]);

  if (loading || !auth) return null;
  return <>{children}</>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider>
          <FilterProvider>{children}</FilterProvider>
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
