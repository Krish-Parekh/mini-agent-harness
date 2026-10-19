"use client";

import { Logout01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/app/providers";
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from "@/components/settings/settings-ui";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  setComposerSelection,
  useComposerSelection,
} from "@/lib/composer-selection";
import { useSandboxProviders } from "@/lib/queries";

function DefaultEnvironment() {
  const selection = useComposerSelection();
  const { data: providers } = useSandboxProviders();
  const fallback = providers?.find((p) => p.default)?.id ?? "local";
  const value =
    providers?.find((p) => p.id === selection.environment && p.available)?.id ??
    fallback;
  const label = (id: string) => providers?.find((p) => p.id === id)?.label ?? id;

  return (
    <Select
      value={value}
      onValueChange={(v) => setComposerSelection({ environment: v as string })}
    >
      <SelectTrigger size="sm" className="min-w-36">
        <SelectValue>{(v: string) => label(v)}</SelectValue>
      </SelectTrigger>
      <SelectContent align="end">
        <SelectGroup>
          {providers?.map((p) => (
            <SelectItem key={p.id} value={p.id} disabled={!p.available}>
              {p.label}
              {!p.available && (
                <span className="text-xs text-muted-foreground">
                  not configured
                </span>
              )}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

export default function GeneralSettingsPage() {
  const { auth, signOut } = useAuth();
  const router = useRouter();

  return (
    <SettingsPage title="General">
      <SettingsGroup>
        <SettingsRow
          title="MiniAgent account"
          description={auth?.user.email ?? "Signed in with GitHub"}
        >
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              await signOut();
              router.push("/");
            }}
          >
            <HugeiconsIcon icon={Logout01Icon} data-icon="inline-start" />
            Sign out
          </Button>
        </SettingsRow>
        <SettingsRow
          title="User ID"
          description="Include this when reporting a problem."
        >
          <code className="truncate text-xs text-muted-foreground">
            {auth?.user.id}
          </code>
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title="New chats">
        <SettingsRow
          title="Default environment"
          description="Where new chats run their sandbox. You can still change it per chat on the home screen."
        >
          <DefaultEnvironment />
        </SettingsRow>
      </SettingsGroup>
    </SettingsPage>
  );
}
