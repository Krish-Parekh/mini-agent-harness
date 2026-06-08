"use client";

import { createContext, useContext, useMemo, useState } from "react";

import type { Repo } from "@/lib/api";

export type Visibility = "all" | "public" | "private";
export type RepoSort = "updated" | "name";

export type RepoFilters = {
  search: string;
  visibility: Visibility;
  owner: string | null;
  language: string | null;
  sort: RepoSort;
};

const DEFAULT_FILTERS: RepoFilters = {
  search: "",
  visibility: "all",
  owner: null,
  language: null,
  sort: "updated",
};

type FilterContextValue = {
  filters: RepoFilters;
  setFilters: (patch: Partial<RepoFilters>) => void;
};

const FilterContext = createContext<FilterContextValue | null>(null);

export function FilterProvider({ children }: { children: React.ReactNode }) {
  const [filters, setState] = useState<RepoFilters>(DEFAULT_FILTERS);
  const value = useMemo<FilterContextValue>(
    () => ({
      filters,
      setFilters: (patch) => setState((prev) => ({ ...prev, ...patch })),
    }),
    [filters],
  );
  return <FilterContext value={value}>{children}</FilterContext>;
}

export function useFilters() {
  const ctx = useContext(FilterContext);
  if (!ctx) throw new Error("useFilters must be used within FilterProvider");
  return ctx;
}

export function repoFacets(repos: Repo[]) {
  const owners = [...new Set(repos.map((r) => r.owner))].sort();
  const languages = [
    ...new Set(repos.map((r) => r.language).filter((l): l is string => !!l)),
  ].sort();
  return { owners, languages };
}

export function filterRepos(repos: Repo[], f: RepoFilters): Repo[] {
  const q = f.search.trim().toLowerCase();
  const matched = repos.filter((r) => {
    if (
      q &&
      !r.full_name.toLowerCase().includes(q) &&
      !r.description?.toLowerCase().includes(q)
    )
      return false;
    if (f.visibility === "public" && r.private) return false;
    if (f.visibility === "private" && !r.private) return false;
    if (f.owner && r.owner !== f.owner) return false;
    if (f.language && r.language !== f.language) return false;
    return true;
  });
  return matched.sort((a, b) =>
    f.sort === "name"
      ? a.name.localeCompare(b.name)
      : b.updated_at.localeCompare(a.updated_at),
  );
}

export function activeFilterCount(f: RepoFilters): number {
  return (
    (f.visibility !== "all" ? 1 : 0) +
    (f.owner ? 1 : 0) +
    (f.language ? 1 : 0) +
    (f.sort !== "updated" ? 1 : 0)
  );
}
