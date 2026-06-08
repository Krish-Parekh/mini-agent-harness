"use client";

import { FilterMailIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  activeFilterCount,
  repoFacets,
  useFilters,
  type RepoSort,
  type Visibility,
} from "@/lib/filters";
import { useRepos } from "@/lib/queries";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

export function FilterPopover() {
  const { filters, setFilters } = useFilters();
  const { data } = useRepos();
  const { owners, languages } = repoFacets(data ?? []);
  const count = activeFilterCount(filters);

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" />}>
        <HugeiconsIcon icon={FilterMailIcon} data-icon="inline-start" />
        Filter
        {count > 0 && <Badge variant="secondary">{count}</Badge>}
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-72 flex-col gap-4">
        <Field label="Visibility">
          <ToggleGroup
            variant="outline"
            value={[filters.visibility]}
            onValueChange={(v) =>
              v[0] && setFilters({ visibility: v[0] as Visibility })
            }
          >
            <ToggleGroupItem value="all">All</ToggleGroupItem>
            <ToggleGroupItem value="public">Public</ToggleGroupItem>
            <ToggleGroupItem value="private">Private</ToggleGroupItem>
          </ToggleGroup>
        </Field>

        <Field label="Owner">
          <Select
            value={filters.owner ?? "all"}
            onValueChange={(v) =>
              setFilters({ owner: v === "all" ? null : (v as string) })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="All owners" />
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
        </Field>

        <Field label="Language">
          <Select
            value={filters.language ?? "all"}
            onValueChange={(v) =>
              setFilters({ language: v === "all" ? null : (v as string) })
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="All languages" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="all">All languages</SelectItem>
                {languages.map((l) => (
                  <SelectItem key={l} value={l}>
                    {l}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>

        <Field label="Sort by">
          <ToggleGroup
            variant="outline"
            value={[filters.sort]}
            onValueChange={(v) =>
              v[0] && setFilters({ sort: v[0] as RepoSort })
            }
          >
            <ToggleGroupItem value="updated">Recently updated</ToggleGroupItem>
            <ToggleGroupItem value="name">Name</ToggleGroupItem>
          </ToggleGroup>
        </Field>
      </PopoverContent>
    </Popover>
  );
}
