"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api, type McpConnection } from "@/lib/api";
import { messageFor } from "@/lib/errors";

function ConnectionRow({
  connection,
  onDelete,
}: {
  connection: McpConnection;
  onDelete: () => void;
}) {
  const [result, setResult] = useState<string | null>(null);
  const test = useMutation({
    mutationFn: () => api.testMcpConnection(connection.id),
    onSuccess: (r) =>
      setResult(
        r.ok
          ? `${r.tools.length} tool${r.tools.length === 1 ? "" : "s"}: ${r.tools.join(", ")}`
          : `Failed: ${r.error ?? "unknown error"}`,
      ),
    onError: (e) => setResult(`Failed: ${messageFor(e)}`),
  });

  return (
    <div className="border-b py-3 last:border-b-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-medium">
            {connection.name}
            {connection.auth_header && (
              <Badge variant="secondary">authenticated</Badge>
            )}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {connection.url}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => test.mutate()}
            disabled={test.isPending}
          >
            {test.isPending ? "Testing…" : "Test"}
          </Button>
          <Button size="sm" variant="outline" onClick={onDelete}>
            Remove
          </Button>
        </div>
      </div>
      {result && (
        <p className="mt-2 break-words text-xs text-muted-foreground">{result}</p>
      )}
    </div>
  );
}

export function McpCard() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [authValue, setAuthValue] = useState("");

  const { data: connections, isPending } = useQuery({
    queryKey: ["mcp-connections"],
    queryFn: api.mcpConnections,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["mcp-connections"] });

  const create = useMutation({
    mutationFn: () =>
      api.createMcpConnection({
        name: name.trim(),
        url: url.trim(),
        auth_header: authHeader.trim() || null,
        auth_value: authValue.trim() || null,
      }),
    onSuccess: () => {
      setName("");
      setUrl("");
      setAuthHeader("");
      setAuthValue("");
      invalidate();
      toast.success("MCP server added");
    },
    onError: (e) => toast.error(messageFor(e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteMcpConnection(id),
    onSuccess: invalidate,
    onError: (e) => toast.error(messageFor(e)),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>MCP servers</CardTitle>
        <CardDescription>
          Remote Model Context Protocol servers. Their tools become available to
          the agent in chats where you enable them.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isPending ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner className="size-4" />
            Loading…
          </div>
        ) : !connections?.length ? (
          <p className="text-sm text-muted-foreground">
            No servers connected yet.
          </p>
        ) : (
          <div>
            {connections.map((connection) => (
              <ConnectionRow
                key={connection.id}
                connection={connection}
                onDelete={() => remove.mutate(connection.id)}
              />
            ))}
          </div>
        )}

        <form
          className="space-y-2 rounded-lg border p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && url.trim()) create.mutate();
          }}
        >
          <p className="text-sm font-medium">Add a server</p>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. Linear)"
          />
          <Input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://mcp.example.com/mcp"
          />
          <div className="flex gap-2">
            <Input
              value={authHeader}
              onChange={(e) => setAuthHeader(e.target.value)}
              placeholder="Auth header (optional)"
            />
            <Input
              value={authValue}
              onChange={(e) => setAuthValue(e.target.value)}
              placeholder="Value (optional)"
              type="password"
            />
          </div>
          <Button
            type="submit"
            disabled={!name.trim() || !url.trim() || create.isPending}
          >
            {create.isPending ? "Adding…" : "Add server"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
