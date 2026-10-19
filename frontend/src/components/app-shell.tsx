"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { useAuth } from "@/app/providers";
import { AppSidebar } from "@/components/app-sidebar";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";

function FullScreen({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-svh items-center justify-center px-6 pb-16">
      {children}
    </main>
  );
}

function SignIn({ onSignIn }: { onSignIn: () => void }) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <HugeiconsIcon icon={Github01Icon} />
        </EmptyMedia>
        <EmptyTitle>Sign in with GitHub</EmptyTitle>
        <EmptyDescription>
          MiniAgent runs against your GitHub repositories, so your GitHub account
          is your account here — there is nothing else to sign up for.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onSignIn}>
          <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
          Continue with GitHub
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function NotConfigured() {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>Supabase is not configured</EmptyTitle>
        <EmptyDescription>
          Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in
          frontend/.env.local — see frontend/.env.example.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { loading, auth, configured, signIn } = useAuth();

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
        <Spinner className="size-5 text-muted-foreground" />
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
      <AppSidebar />
      <SidebarInset className="min-h-0 overflow-y-auto">{children}</SidebarInset>
    </SidebarProvider>
  );
}
