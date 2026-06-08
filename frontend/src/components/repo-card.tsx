"use client";

import { useState } from "react";

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
import type { Repo } from "@/lib/api";
import { useStartChat } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function RepoCard({ repo }: { repo: Repo }) {
  const [expanded, setExpanded] = useState(false);
  const startChat = useStartChat();
  const canExpand = (repo.description?.length ?? 0) > 100;

  return (
    <Card className="flex h-full flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="truncate">{repo.name}</CardTitle>
          <Badge
            className={cn(
              repo.private
                ? "bg-[#EFA417]/15 text-[#EFA417]"
                : "bg-[#13B17F]/15 text-[#13B17F]",
            )}
          >
            {repo.private ? "Private" : "Public"}
          </Badge>
        </div>
        <CardDescription className="truncate">{repo.full_name}</CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-3">
        {repo.description && (
          <div>
            <p
              className={cn(
                "text-sm text-muted-foreground",
                !expanded && "line-clamp-2",
              )}
            >
              {repo.description}
            </p>
            {canExpand && (
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? "less" : "more"}
              </Button>
            )}
          </div>
        )}
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          disabled={startChat.isPending}
          onClick={() => startChat.mutate(repo)}
        >
          {startChat.isPending ? "Starting…" : "Start chat"}
        </Button>
      </CardFooter>
    </Card>
  );
}
