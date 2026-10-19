"use client";

import { ArrowDown01Icon, GitBranchIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import type { Branch } from "@/lib/api";

export function BranchPicker({
  value,
  branches,
  loading,
  error,
  onChange,
  disabled,
}: {
  value: string | null;
  branches: Branch[] | undefined;
  loading: boolean;
  error: boolean;
  onChange: (branch: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        disabled={disabled}
        render={<Button variant="ghost" size="sm" className="max-w-48" />}
      >
        <HugeiconsIcon icon={GitBranchIcon} data-icon="inline-start" />
        <span className="truncate">{value ?? "Branch"}</span>
        <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 gap-0 p-0">
        <Command>
          <CommandInput placeholder="Search branches…" />
          <CommandList>
            {loading ? (
              <div className="flex flex-col gap-2 p-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-6" />
                ))}
              </div>
            ) : error ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Couldn&apos;t load branches.
              </p>
            ) : (
              <>
                <CommandEmpty>No branches match.</CommandEmpty>
                <CommandGroup>
                  {branches?.map((branch) => (
                    <CommandItem
                      key={branch.name}
                      value={branch.name}
                      data-checked={branch.name === value}
                      onSelect={() => {
                        onChange(branch.name);
                        setOpen(false);
                      }}
                    >
                      <span className="truncate">{branch.name}</span>
                      {branch.default && <Badge variant="outline">default</Badge>}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
