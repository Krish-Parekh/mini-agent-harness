"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { api, ApiError, type Repo } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export default function ReposPage() {
  const router = useRouter();
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    api
      .repos()
      .then(setRepos)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/");
        else setError("Failed to load repositories.");
      });
  }, [router]);

  const filtered = useMemo(() => {
    if (!repos) return [];
    const q = query.trim().toLowerCase();
    return q
      ? repos.filter((r) => r.full_name.toLowerCase().includes(q))
      : repos;
  }, [repos, query]);

  async function startChat(repo: Repo) {
    setStarting(repo.full_name);
    try {
      const info = await api.createConversation({
        repo: repo.full_name,
        branch: repo.default_branch,
      });
      router.push(`/chat/${info.id}`);
    } catch {
      setError(`Could not start a session for ${repo.full_name}.`);
      setStarting(null);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Your repositories</h1>
        <p className="text-muted-foreground text-sm">
          Pick a repository to start a coding session.
        </p>
      </div>

      <Input
        placeholder="Search repositories…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="mb-4"
      />

      {error && <p className="text-destructive mb-4 text-sm">{error}</p>}

      {repos === null && !error && (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      )}

      {repos !== null && filtered.length === 0 && (
        <p className="text-muted-foreground text-sm">No repositories match.</p>
      )}

      <div className="space-y-3">
        {filtered.map((repo) => (
          <Card key={repo.full_name}>
            <CardContent className="flex items-center justify-between gap-4 py-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{repo.full_name}</span>
                  <Badge variant={repo.private ? "secondary" : "outline"}>
                    {repo.private ? "private" : "public"}
                  </Badge>
                </div>
                {repo.description && (
                  <p className="text-muted-foreground mt-1 truncate text-sm">
                    {repo.description}
                  </p>
                )}
                <p className="text-muted-foreground mt-1 text-xs">
                  default branch: {repo.default_branch}
                </p>
              </div>
              <Button
                onClick={() => startChat(repo)}
                disabled={starting !== null}
              >
                {starting === repo.full_name ? "Starting…" : "Start chat"}
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </main>
  );
}
