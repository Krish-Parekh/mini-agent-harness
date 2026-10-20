"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { usePathname } from "next/navigation";

import { useAuth } from "@/app/providers";
import { AppSidebar } from "@/components/app-sidebar";
import { Pill } from "@/components/bui/button";
import { LoadingState } from "@/components/bui/loading-state";
import { SettingsSidebar } from "@/components/settings/settings-sidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

function FullScreen({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-page px-6 pb-16">
      {children}
    </main>
  );
}

function ShellCard({
  icon,
  title,
  children,
}: {
  icon?: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex w-full max-w-sm animate-[fade-up_320ms_var(--ease-out-strong)_both] flex-col items-center gap-4 rounded-window bg-surface px-6 py-7 text-center shadow-card">
      {icon && (
        <span className="flex size-10 items-center justify-center rounded-card bg-hover-2 text-ink">
          {icon}
        </span>
      )}
      <div className="flex flex-col gap-1.5">
        <h1 className="text-[15px] font-semibold text-ink">{title}</h1>
        {children}
      </div>
    </section>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded-chip bg-hover px-1 py-0.5 font-mono text-[12px] text-ink">
      {children}
    </code>
  );
}

function SignIn({ onSignIn }: { onSignIn: () => void }) {
  return (
    <ShellCard
      icon={<HugeiconsIcon icon={Github01Icon} className="size-5" />}
      title="Sign in with GitHub"
    >
      <p className="text-[13.5px] leading-relaxed text-ink-2">
        MiniAgent runs against your GitHub repositories, so your GitHub account
        is your account here. There is nothing else to sign up for.
      </p>
      <Pill variant="primary" onClick={onSignIn} className="mt-3 self-center">
        <HugeiconsIcon icon={Github01Icon} className="size-4" />
        Continue with GitHub
      </Pill>
    </ShellCard>
  );
}

function NotConfigured() {
  return (
    <ShellCard title="Supabase is not configured">
      <p className="text-[13.5px] leading-relaxed text-ink-2">
        Set <Code>NEXT_PUBLIC_SUPABASE_URL</Code> and{" "}
        <Code>NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY</Code> in{" "}
        <Code>frontend/.env.local</Code> (see <Code>frontend/.env.example</Code>
        ).
      </p>
    </ShellCard>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { loading, auth, configured, signIn } = useAuth();
  const pathname = usePathname();

  if (!configured) {
    return (
      <FullScreen>
        <NotConfigured />
      </FullScreen>
    );
  }
  if (loading) {
    return (
      <FullScreen>
        <LoadingState label="Loading" />
      </FullScreen>
    );
  }
  if (!auth) {
    return (
      <FullScreen>
        <SignIn onSignIn={() => void signIn()} />
      </FullScreen>
    );
  }

  return (
    <SidebarProvider className="h-svh overflow-hidden">
      {pathname.startsWith("/settings") ? <SettingsSidebar /> : <AppSidebar />}
      <SidebarInset className="min-h-0 overflow-y-auto">{children}</SidebarInset>
    </SidebarProvider>
  );
}
