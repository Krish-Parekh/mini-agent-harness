"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { useAuth } from "@/app/providers";
import { RepoBrowser } from "@/components/repo-browser";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <span className="grid size-7 place-items-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
        M
      </span>
      <span className="text-lg font-semibold tracking-tight">MiniAgent</span>
    </div>
  );
}

function Account({ login, avatar }: { login: string; avatar: string | null }) {
  return (
    <div className="flex items-center gap-2">
      <Avatar className="size-7">
        <AvatarImage src={avatar ?? undefined} alt={login} />
        <AvatarFallback className="text-xs">
          {login.slice(0, 2).toUpperCase()}
        </AvatarFallback>
      </Avatar>
      <span className="text-sm font-medium">{login}</span>
    </div>
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

function Reconnect({ onSignIn }: { onSignIn: () => void }) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <HugeiconsIcon icon={Github01Icon} />
        </EmptyMedia>
        <EmptyTitle>Reconnect GitHub</EmptyTitle>
        <EmptyDescription>
          You&apos;re signed in, but MiniAgent no longer holds a GitHub token —
          either you disconnected it or it was revoked on GitHub.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onSignIn}>
          <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
          Reconnect GitHub
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
          Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in
          frontend/.env.local — see frontend/.env.example.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

export default function Home() {
  const { loading, auth, configured, signIn } = useAuth();
  const github = auth?.github;

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-5xl flex-col px-6">
      <header className="flex h-16 items-center justify-between">
        <Brand />
        {github?.connected && github.login && (
          <Account login={github.login} avatar={github.avatar_url} />
        )}
      </header>

      {loading ? (
        <div className="grid flex-1 gap-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : github?.connected ? (
        <div className="flex-1 py-4">
          <RepoBrowser />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center pb-16">
          {!configured ? (
            <NotConfigured />
          ) : auth ? (
            <Reconnect onSignIn={signIn} />
          ) : (
            <SignIn onSignIn={signIn} />
          )}
        </div>
      )}
    </main>
  );
}
