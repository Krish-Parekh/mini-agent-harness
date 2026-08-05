import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

export const supabaseConfigured = Boolean(url && publishableKey);

export const supabase = createClient(url ?? "http://localhost", publishableKey ?? "anon", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
    flowType: "pkce",
  },
});

export function signInWithGitHub(redirectTo?: string) {
  return supabase.auth.signInWithOAuth({
    provider: "github",
    options: {
      scopes: "repo",
      redirectTo: redirectTo ?? window.location.origin,
    },
  });
}

export async function accessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
