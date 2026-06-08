"use client";

import { useMemo, useState } from "react";

import {
  Alert02Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  FolderLibraryIcon,
  Search01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import { FilterPopover } from "@/components/filter-popover";
import { ImportRepoDialog } from "@/components/import-repo-dialog";
import { RepoCard } from "@/components/repo-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";
import { Skeleton } from "@/components/ui/skeleton";
import { filterRepos, useFilters } from "@/lib/filters";
import { useRepos } from "@/lib/queries";

const PAGE_SIZE = 8;

/** Page numbers to render, with `null` marking an elided gap. */
function pageItems(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const items: (number | null)[] = [1];
  const left = Math.max(2, current - 1);
  const right = Math.min(total - 1, current + 1);
  if (left > 2) items.push(null);
  for (let p = left; p <= right; p++) items.push(p);
  if (right < total - 1) items.push(null);
  items.push(total);
  return items;
}

export function RepoBrowser() {
  const { filters, setFilters } = useFilters();
  const { data, isPending, isError, refetch } = useRepos();
  const [page, setPage] = useState(1);

  const repos = useMemo(
    () => filterRepos(data ?? [], filters),
    [data, filters],
  );

  // Searching or filtering changes the result set, so jump back to the first page.
  // Adjusting state during render (vs. an effect) avoids a cascading re-render.
  const filterSig = JSON.stringify(filters);
  const [prevSig, setPrevSig] = useState(filterSig);
  if (filterSig !== prevSig) {
    setPrevSig(filterSig);
    setPage(1);
  }

  const search = (
    <div className="flex items-center gap-3">
      <InputGroup className="flex-1">
        <InputGroupAddon>
          <HugeiconsIcon icon={Search01Icon} />
        </InputGroupAddon>
        <InputGroupInput
          type="search"
          placeholder="Search repositories…"
          value={filters.search}
          onChange={(e) => setFilters({ search: e.target.value })}
        />
      </InputGroup>
      <ImportRepoDialog />
      <FilterPopover />
    </div>
  );

  if (isPending) {
    return (
      <div className="flex flex-col gap-6">
        {search}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-6">
        {search}
        <Alert variant="destructive">
          <HugeiconsIcon icon={Alert02Icon} />
          <AlertTitle>Failed to load repositories</AlertTitle>
          <AlertDescription>
            Something went wrong fetching your repositories.
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const pageCount = Math.max(1, Math.ceil(repos.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const start = (current - 1) * PAGE_SIZE;
  const pageRepos = repos.slice(start, start + PAGE_SIZE);

  return (
    <div className="flex flex-col gap-6">
      {search}

      {repos.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <HugeiconsIcon icon={FolderLibraryIcon} />
            </EmptyMedia>
            <EmptyTitle>No repositories match</EmptyTitle>
            <EmptyDescription>
              Try adjusting your search or filters.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-2">
            {pageRepos.map((repo) => (
              <RepoCard key={repo.full_name} repo={repo} />
            ))}
          </div>

          {pageCount > 1 && (
            <nav
              aria-label="Repository pages"
              className="flex flex-wrap items-center justify-center gap-1"
            >
              <Button
                variant="ghost"
                size="sm"
                disabled={current === 1}
                onClick={() => setPage(current - 1)}
              >
                <HugeiconsIcon icon={ArrowLeft01Icon} data-icon="inline-start" />
                Prev
              </Button>
              {pageItems(current, pageCount).map((p, i) =>
                p === null ? (
                  <span
                    key={`gap-${i}`}
                    className="px-2 text-sm text-muted-foreground"
                  >
                    …
                  </span>
                ) : (
                  <Button
                    key={p}
                    variant={p === current ? "default" : "ghost"}
                    size="sm"
                    aria-current={p === current ? "page" : undefined}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </Button>
                ),
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={current === pageCount}
                onClick={() => setPage(current + 1)}
              >
                Next
                <HugeiconsIcon icon={ArrowRight01Icon} data-icon="inline-end" />
              </Button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
