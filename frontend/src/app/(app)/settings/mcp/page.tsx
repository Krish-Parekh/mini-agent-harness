"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import {
  SettingsEmpty,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from "@/components/settings/settings-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type McpConnection } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { queryKeys, useMcpConnections } from "@/lib/queries";

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
    <SettingsRow
      title={connection.name}
      description={
        <span className="flex flex-col gap-0.5">
          <span className="truncate">
            {connection.url}
            {connection.auth_header && " · authenticated"}
          </span>
          {result && <span className="text-xs">{result}</span>}
        </span>
      }
    >
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
    </SettingsRow>
  );
}

export default function McpSettingsPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authHeader, setAuthHeader] = useState("");
  const [authValue, setAuthValue] = useState("");
  const { data: connections, isPending } = useMcpConnections();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.mcpConnections });

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
    <SettingsPage title="MCP servers">
      <SettingsGroup
        title="Your servers"
        description="Remote Model Context Protocol servers. Their tools become available in chats where you enable them."
      >
        {isPending ? (
          <div className="flex flex-col gap-3 py-4">
            <Skeleton className="h-5 w-1/2" />
          </div>
        ) : !connections?.length ? (
          <SettingsEmpty>No servers connected yet.</SettingsEmpty>
        ) : (
          connections.map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              onDelete={() => remove.mutate(connection.id)}
            />
          ))
        )}
      </SettingsGroup>

      <SettingsGroup title="Add a server">
        <form
          autoComplete="off"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && url.trim()) create.mutate();
          }}
        >
          <SettingsRow title="Name" description="Shown in chats, e.g. Linear.">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Linear"
              className="h-8 sm:w-72"
            />
          </SettingsRow>
          <SettingsRow
            title="URL"
            description="https, or http on localhost."
          >
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://mcp.example.com/mcp"
              className="h-8 sm:w-72"
            />
          </SettingsRow>
          <SettingsRow
            title="Authentication"
            description="Optional header sent with every request."
          >
            <div className="flex gap-2 sm:w-72">
              <Input
                value={authHeader}
                onChange={(e) => setAuthHeader(e.target.value)}
                placeholder="Header"
                autoComplete="off"
                className="h-8"
              />
              <Input
                value={authValue}
                onChange={(e) => setAuthValue(e.target.value)}
                placeholder="Value"
                type="password"
                autoComplete="new-password"
                className="h-8"
              />
            </div>
          </SettingsRow>
          <div className="flex justify-end py-4">
            <Button
              type="submit"
              size="sm"
              disabled={!name.trim() || !url.trim() || create.isPending}
            >
              {create.isPending ? "Adding…" : "Add server"}
            </Button>
          </div>
        </form>
      </SettingsGroup>
    </SettingsPage>
  );
}
