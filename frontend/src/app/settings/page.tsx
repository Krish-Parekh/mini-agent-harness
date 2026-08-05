"use client";

import { Github01Icon, Logout01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/app/providers";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { messageFor } from "@/lib/errors";

function GitHubCard() {
  const { auth, signIn, disconnectGitHub } = useAuth();
  const [pending, setPending] = useState(false);
  const github = auth?.github;

  async function onDisconnect() {
    setPending(true);
    try {
      await disconnectGitHub();
      toast.success("GitHub disconnected");
    } catch (e) {
      toast.error(messageFor(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HugeiconsIcon icon={Github01Icon} className="size-4" />
          GitHub
        </CardTitle>
        <CardDescription>
          The connection MiniAgent uses to clone your repositories and open pull
          requests on your behalf.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {github?.connected ? (
          <div className="flex items-center gap-3">
            <Avatar className="size-10">
              <AvatarImage
                src={github.avatar_url ?? undefined}
                alt={github.login ?? "GitHub"}
              />
              <AvatarFallback>
                {(github.login ?? "GH").slice(0, 2).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="grid gap-0.5">
              <span className="font-medium">{github.login}</span>
              {github.connected_at && (
                <span className="text-xs text-muted-foreground">
                  Connected {new Date(github.connected_at).toLocaleDateString()}
                </span>
              )}
            </div>
            <Badge variant="secondary" className="ml-auto">
              Connected
            </Badge>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <p className="text-sm text-muted-foreground">
              No GitHub token stored. Reconnect to browse repositories and open
              pull requests.
            </p>
            <Badge variant="outline" className="ml-auto">
              Disconnected
            </Badge>
          </div>
        )}
      </CardContent>
      <CardFooter className="gap-2">
        {github?.connected ? (
          <Button variant="outline" disabled={pending} onClick={onDisconnect}>
            {pending ? "Disconnecting…" : "Disconnect GitHub"}
          </Button>
        ) : (
          <Button onClick={() => void signIn()}>
            <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
            Reconnect GitHub
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}

function AccountCard() {
  const { auth, signOut } = useAuth();
  const router = useRouter();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>
          Signing out ends your session here. It does not revoke MiniAgent&apos;s
          GitHub access — use Disconnect above for that.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Email</span>
          <span className="truncate">{auth?.user.email ?? "—"}</span>
        </div>
        <Separator />
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">User ID</span>
          <code className="truncate text-xs">{auth?.user.id}</code>
        </div>
      </CardContent>
      <CardFooter>
        <Button
          variant="outline"
          onClick={async () => {
            await signOut();
            router.push("/");
          }}
        >
          <HugeiconsIcon icon={Logout01Icon} data-icon="inline-start" />
          Sign out
        </Button>
      </CardFooter>
    </Card>
  );
}

export default function SettingsPage() {
  const { loading, auth } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !auth) router.replace("/");
  }, [loading, auth, router]);

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-2xl flex-col gap-6 px-6 py-10">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Your account and connected services.
          </p>
        </div>
        <Button variant="ghost" nativeButton={false} render={<Link href="/" />}>
          Back
        </Button>
      </header>

      {loading || !auth ? (
        <>
          <Skeleton className="h-52 rounded-xl" />
          <Skeleton className="h-52 rounded-xl" />
        </>
      ) : (
        <>
          <GitHubCard />
          <AccountCard />
        </>
      )}
    </main>
  );
}
