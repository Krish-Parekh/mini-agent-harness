"use client";

import {
  ArrowDown01Icon,
  CloudIcon,
  ComputerIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { SandboxProvider } from "@/lib/api";

function iconFor(id: string) {
  return id === "local" ? ComputerIcon : CloudIcon;
}

export function EnvironmentPicker({
  value,
  providers,
  onChange,
}: {
  value: string | null;
  providers: SandboxProvider[] | undefined;
  onChange: (provider: string) => void;
}) {
  const selected = providers?.find((p) => p.id === value);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={!providers}
        render={<Button variant="ghost" size="sm" />}
      >
        <HugeiconsIcon icon={iconFor(value ?? "local")} data-icon="inline-start" />
        {selected?.label ?? "Environment"}
        <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Environment</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={value ?? ""}
            onValueChange={(v) => onChange(v as string)}
          >
            {providers?.map((p) => (
              <DropdownMenuRadioItem
                key={p.id}
                value={p.id}
                disabled={!p.available}
                title={p.reason ?? undefined}
              >
                <HugeiconsIcon icon={iconFor(p.id)} />
                {p.label}
                {!p.available && (
                  <span className="ml-auto text-xs whitespace-nowrap text-muted-foreground">
                    not configured
                  </span>
                )}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
