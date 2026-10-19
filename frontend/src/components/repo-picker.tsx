"use client";

import {
  ArrowDown01Icon,
  FolderLibraryIcon,
  GitForkIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useState } from "react";

import { ImportRepoDialog } from "@/components/import-repo-dialog";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { Repo } from "@/lib/api";
import { filterRepos, repoFacets, type Visibility } from "@/lib/filters";
import { useRepos } from "@/lib/queries";

export function RepoPicker({
  value,
  onChange,
  disabled,
}: {
  value: string | null;
  onChange: (repo: Repo) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [visibility, setVisibility] = useState<Visibility>("all");
  const [owner, setOwner] = useState<string | null>(null);
  const { data, isPending, isError } = useRepos(!disabled);

  const { owners } = repoFacets(data ?? []);
  const repos = filterRepos(data ?? [], {
    search: "",
    visibility,
    owner,
    language: null,
    sort: "updated",
  });

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          disabled={disabled}
          render={<Button variant="ghost" size="sm" className="max-w-64" />}
        >
          <HugeiconsIcon icon={FolderLibraryIcon} data-icon="inline-start" />
          <span className="truncate">{value ?? "Select repository"}</span>
          <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 gap-0 p-0">
          <Command>
            <CommandInput placeholder="Search repositories…" />
            <div className="flex items-center gap-2 px-1 pt-2">
              <ToggleGroup
                variant="outline"
                size="sm"
                value={[visibility]}
                onValueChange={(v) => v[0] && setVisibility(v[0] as Visibility)}
              >
                <ToggleGroupItem value="all">All</ToggleGroupItem>
                <ToggleGroupItem value="public">Public</ToggleGroupItem>
                <ToggleGroupItem value="private">Private</ToggleGroupItem>
              </ToggleGroup>
              <Select
                value={owner ?? "all"}
                onValueChange={(v) => setOwner(v === "all" ? null : (v as string))}
              >
                <SelectTrigger size="sm" className="min-w-0 flex-1">
                  <SelectValue>
                    {(v: string) => (v === "all" ? "All owners" : v)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="all">All owners</SelectItem>
                    {owners.map((o) => (
                      <SelectItem key={o} value={o}>
                        {o}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <CommandList>
              {isPending ? (
                <div className="flex flex-col gap-2 p-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-6" />
                  ))}
                </div>
              ) : isError ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Couldn&apos;t load repositories.
                </p>
              ) : (
                <>
                  <CommandEmpty>No repositories match.</CommandEmpty>
                  <CommandGroup>
                    {repos.map((repo) => (
                      <CommandItem
                        key={repo.full_name}
                        value={repo.full_name}
                        keywords={repo.description ? [repo.description] : []}
                        data-checked={repo.full_name === value}
                        onSelect={() => {
                          onChange(repo);
                          setOpen(false);
                        }}
                      >
                        <span className="truncate">{repo.full_name}</span>
                        {repo.private && (
                          <span className="text-xs text-muted-foreground">
                            Private
                          </span>
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </>
              )}
              <CommandSeparator />
              <CommandGroup forceMount>
                <CommandItem
                  value="__import__"
                  forceMount
                  onSelect={() => {
                    setOpen(false);
                    setImportOpen(true);
                  }}
                >
                  <HugeiconsIcon icon={GitForkIcon} />
                  Import repository…
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <ImportRepoDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        onImported={onChange}
      />
    </>
  );
}
