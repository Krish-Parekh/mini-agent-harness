"use client";

import { useMemo, useState } from "react";

import { type SkillInfo } from "@/lib/api";
import { useSkillBody, useSkills } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { MessageResponse } from "@/components/ai-elements/message";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { HugeiconsIcon } from "@hugeicons/react";
import { Alert02Icon, BookOpen01Icon } from "@hugeicons/core-free-icons";

// The frontmatter is library bookkeeping (name/description) shown in the
// header already; strip it so the body renders as clean markdown.
function stripFrontmatter(content: string): string {
  if (!content.startsWith("---")) return content;
  const end = content.indexOf("\n---", 3);
  return end === -1 ? content : content.slice(end + 4).trimStart();
}

function SkillRow({
  skill,
  selected,
  onClick,
}: {
  skill: SkillInfo;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full flex-col gap-0.5 rounded-md px-2.5 py-2 text-left transition-colors",
        selected ? "bg-muted" : "hover:bg-muted/50",
      )}
    >
      <span className="text-sm font-medium">{skill.name}</span>
      <span className="line-clamp-2 text-xs text-muted-foreground">
        {skill.description}
      </span>
    </button>
  );
}

function SkillDetail({ skill }: { skill: SkillInfo }) {
  const { data, isPending, isError, refetch } = useSkillBody(
    skill.name,
    skill.repo,
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <span className="font-mono text-sm font-medium">{skill.name}</span>
        <Badge variant="outline">
          {skill.scope === "global" ? "global" : skill.repo}
        </Badge>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="max-w-3xl p-4">
          {isPending ? (
            <Spinner className="size-4" />
          ) : isError ? (
            <div className="flex flex-col items-start gap-1">
              <p className="text-destructive text-sm">
                Couldn&apos;t load this skill.
              </p>
              <Button variant="link" size="sm" className="h-auto p-0" onClick={() => refetch()}>
                Retry
              </Button>
            </div>
          ) : (
            <MessageResponse>{stripFrontmatter(data.content)}</MessageResponse>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

export default function SkillsPage() {
  const { data, isPending, isError, refetch } = useSkills();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const groups = useMemo(() => {
    const byGroup = new Map<string, SkillInfo[]>();
    for (const s of data ?? []) {
      const group = s.scope === "global" ? "Global" : s.repo ?? "Unknown";
      byGroup.set(group, [...(byGroup.get(group) ?? []), s]);
    }
    // Global last, mirroring how the agent resolves repo skills first.
    return [...byGroup.entries()].sort(([a], [b]) =>
      a === "Global" ? 1 : b === "Global" ? -1 : a.localeCompare(b),
    );
  }, [data]);

  const keyOf = (s: SkillInfo) => `${s.repo ?? "global"}/${s.name}`;
  const selected =
    (data ?? []).find((s) => keyOf(s) === selectedKey) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
        <SidebarTrigger />
        <h1 className="text-sm font-semibold">Skills</h1>
        {data && data.length > 0 && (
          <span className="text-xs text-muted-foreground">{data.length}</span>
        )}
      </header>

      {isPending ? (
        <div className="w-72 space-y-2 p-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : isError ? (
        <div className="p-6">
          <Alert variant="destructive" className="max-w-md">
            <HugeiconsIcon icon={Alert02Icon} />
            <AlertTitle>Failed to load skills</AlertTitle>
            <AlertDescription>
              Something went wrong fetching the skill library.
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => refetch()}
              >
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        </div>
      ) : (data ?? []).length === 0 ? (
        <div className="flex flex-1 items-center justify-center">
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <HugeiconsIcon icon={BookOpen01Icon} />
              </EmptyMedia>
              <EmptyTitle>No skills yet</EmptyTitle>
              <EmptyDescription>
                The agent distills reusable skills from substantial finished
                runs. Complete a real multi-step task and they&apos;ll show up
                here.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <ScrollArea className="w-72 shrink-0 border-r">
            <div className="space-y-4 p-3">
              {groups.map(([group, skills]) => (
                <div key={group}>
                  <p className="px-2.5 pb-1 font-mono text-xs text-muted-foreground">
                    {group}
                  </p>
                  <div className="space-y-0.5">
                    {skills.map((skill) => (
                      <SkillRow
                        key={keyOf(skill)}
                        skill={skill}
                        selected={selectedKey === keyOf(skill)}
                        onClick={() => setSelectedKey(keyOf(skill))}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>

          {selected ? (
            <SkillDetail key={keyOf(selected)} skill={selected} />
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-muted-foreground">
                Select a skill to read it.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
