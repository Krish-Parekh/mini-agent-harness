"use client";

import { Github01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useState } from "react";
import { toast } from "sonner";

import { useAuth } from "@/app/providers";
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from "@/components/settings/settings-ui";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { messageFor } from "@/lib/errors";

export default function GitHubSettingsPage() {
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
    <SettingsPage title="GitHub">
      <SettingsGroup>
        {github?.connected ? (
          <SettingsRow
            title={
              <span className="flex items-center gap-2">
                <Avatar className="size-5">
                  <AvatarImage
                    src={github.avatar_url ?? undefined}
                    alt={github.login ?? "GitHub"}
                  />
                  <AvatarFallback className="text-[10px]">
                    {(github.login ?? "GH").slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                {github.login}
              </span>
            }
            description={
              github.connected_at
                ? `Connected ${new Date(github.connected_at).toLocaleDateString()}. Used to clone your repositories and open pull requests.`
                : "Used to clone your repositories and open pull requests."
            }
          >
            <Button
              variant="outline"
              size="sm"
              disabled={pending}
              onClick={onDisconnect}
            >
              {pending ? "Disconnecting…" : "Disconnect"}
            </Button>
          </SettingsRow>
        ) : (
          <SettingsRow
            title="Not connected"
            description="Connect GitHub to browse repositories, start chats and open pull requests."
          >
            <Button size="sm" onClick={() => void signIn()}>
              <HugeiconsIcon icon={Github01Icon} data-icon="inline-start" />
              Connect GitHub
            </Button>
          </SettingsRow>
        )}
      </SettingsGroup>

      <SettingsGroup title="Access">
        <SettingsRow
          title="Repository scope"
          description="MiniAgent asks GitHub for the repo scope, so it can read and push to the repositories you choose. Disconnecting deletes the stored token; revoke the app on GitHub to remove access entirely."
        />
      </SettingsGroup>
    </SettingsPage>
  );
}
