"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

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
import { api } from "@/lib/api";
import { useGitHubStatus } from "@/lib/queries";

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

function Account({ login }: { login: string }) {
  return (
    <div className="flex items-center gap-2">
      <Avatar className="size-7">
        <AvatarImage src={`https://github.com/${login}.png`} alt={login} />
        <AvatarFallback className="text-xs">
          {login.slice(0, 2).toUpperCase()}
        </AvatarFallback>
      </Avatar>
      <span className="text-sm font-medium">{login}</span>
    </div>
  );
}

export default function Home() {
  const { data, isPending } = useGitHubStatus();
  const connected = data?.connected;

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-5xl flex-col px-6">
      <header className="flex h-16 items-center justify-between">
        <Brand />
        {connected && data?.login && <Account login={data.login} />}
      </header>

      {isPending ? (
        <div className="grid flex-1 gap-4 py-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : connected ? (
        <div className="flex-1 py-4">
          <RepoBrowser />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center pb-16">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <HugeiconsIcon icon={Github01Icon} />
              </EmptyMedia>
              <EmptyTitle>Connect your GitHub</EmptyTitle>
              <EmptyDescription>
                Connect your GitHub account to browse your repositories and start
                a coding session with the agent.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button nativeButton={false} render={<a href={api.loginUrl()} />}>
                <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
                Connect GitHub
              </Button>
            </EmptyContent>
          </Empty>
        </div>
      )}
    </main>
  );
}
