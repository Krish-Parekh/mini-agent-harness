"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api, type ConversationContext, type EnabledItem } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { cn } from "@/lib/utils";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b px-4 py-3 last:border-b-0">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate text-right font-medium">{value}</span>
    </div>
  );
}

function Note({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 240;
  return (
    <div className="space-y-1">
      <pre
        className={cn(
          "whitespace-pre-wrap break-words rounded-md bg-muted/50 p-2 text-xs leading-relaxed",
          !open && long && "line-clamp-6",
        )}
      >
        {text}
      </pre>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-muted-foreground underline"
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}


const SANDBOX_LABELS: Record<string, string> = {
  local: "Local",
  docker: "Docker",
  e2b: "E2B",
  daytona: "Daytona",
  modal: "Modal",
  vercel: "Vercel",
  space: "SPACE",
};

const HOST_GIT = new Set(["local", "docker"]);

export function FailureReference({
  conversationId,
  traceId,
  className,
}: {
  conversationId: string;
  traceId?: string | null;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const reference = traceId
    ? `conversation=${conversationId} trace=${traceId}`
    : `conversation=${conversationId}`;

  return (
    <div className={cn("space-y-1.5", className)}>
      <p className="text-xs text-muted-foreground">Reference</p>
      <code className="block break-all rounded-md bg-muted/60 p-2 text-xs">
        {reference}
      </code>
      <Button
        size="sm"
        variant="outline"
        onClick={() => {
          navigator.clipboard
            .writeText(reference)
            .then(() => setCopied(true))
            .catch(() => setCopied(false));
        }}
      >
        {copied ? "Copied" : "Copy reference"}
      </Button>
      {!traceId && (
        <p className="text-xs text-muted-foreground">
          No trace recorded — tracing was not configured for this run.
        </p>
      )}
    </div>
  );
}

function Toggles({
  title,
  emptyHint,
  items,
  isPending,
  onToggle,
}: {
  title: string;
  emptyHint: React.ReactNode;
  items: EnabledItem[] | undefined;
  isPending: boolean;
  onToggle: (id: string, enabled: boolean) => void;
}) {
  return (
    <Section title={title}>
      {isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !items?.length ? (
        <p className="text-sm text-muted-foreground">{emptyHint}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-sm">{item.name}</span>
                {item.skipped && (
                  <Badge className="bg-[#EFA417]/15 text-[#EFA417]">
                    Skipped: over budget
                  </Badge>
                )}
              </span>
              <Button
                size="sm"
                variant={item.enabled ? "default" : "outline"}
                onClick={() => onToggle(item.id, !item.enabled)}
              >
                {item.enabled ? "Enabled" : "Enable"}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        Changes apply to new runs in this conversation.
      </p>
    </Section>
  );
}

function Extensions({ conversationId }: { conversationId: string }) {
  const queryClient = useQueryClient();

  const skills = useQuery({
    queryKey: ["conversation-skills", conversationId],
    queryFn: () => api.conversationSkills(conversationId),
  });
  const mcp = useQuery({
    queryKey: ["conversation-mcp", conversationId],
    queryFn: () => api.conversationMcp(conversationId),
  });

  const toggleSkill = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.setConversationSkill(conversationId, id, enabled),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["conversation-skills", conversationId],
      }),
    onError: (e) => toast.error(messageFor(e)),
  });

  const toggleMcp = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.setConversationMcp(conversationId, id, enabled),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["conversation-mcp", conversationId],
      }),
    onError: (e) => toast.error(messageFor(e)),
  });

  return (
    <>
      <Toggles
        title="Skills"
        emptyHint={
          <>
            No skills yet —{" "}
            <Link href="/skills" className="underline">
              add one
            </Link>
            .
          </>
        }
        items={skills.data}
        isPending={skills.isPending}
        onToggle={(id, enabled) => toggleSkill.mutate({ id, enabled })}
      />
      <Toggles
        title="MCP servers"
        emptyHint={
          <>
            No servers yet —{" "}
            <Link href="/settings" className="underline">
              connect one
            </Link>
            .
          </>
        }
        items={mcp.data}
        isPending={mcp.isPending}
        onToggle={(id, enabled) => toggleMcp.mutate({ id, enabled })}
      />
    </>
  );
}

export function ContextPanel({
  conversationId,
  context,
  isPending,
}: {
  conversationId: string;
  context: ConversationContext | undefined;
  isPending: boolean;
}) {
  if (isPending && !context) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
        <Spinner className="size-4" />
        Loading context…
      </div>
    );
  }

  if (!context) {
    return (
      <p className="px-4 py-6 text-sm text-muted-foreground">
        Context is unavailable for this conversation.
      </p>
    );
  }

  const { usage, session_changes: changes, counts } = context;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <Section title="Repository">
        <Row label="Repository" value={context.repo ?? "—"} />
        <Row label="Branch" value={context.branch ?? "—"} />
        <Row
          label="Sandbox"
          value={SANDBOX_LABELS[context.sandbox_provider] ?? context.sandbox_provider}
        />
        {context.workspace_dir && (
          <Row
            label={HOST_GIT.has(context.sandbox_provider) ? "Worktree" : "Workspace"}
            value={
              <span title={context.workspace_dir}>
                {context.workspace_dir.split("/").slice(-2).join("/")}
              </span>
            }
          />
        )}
      </Section>

      <Section title="Run">
        <Row label="Status" value={context.status.replace(/_/g, " ")} />
        <Row label="Model" value={context.model} />
        <Row label="Events" value={counts.events} />
        <Row label="Your turns" value={counts.user_turns} />
      </Section>

      {context.sandbox_expired && (
        <Section title="Session changes">
          <p className="text-xs text-muted-foreground">
            The sandbox expired. The diff is no longer available.
          </p>
        </Section>
      )}

      {changes.files > 0 && (
        <Section title="Session changes">
          <Row label="Files" value={changes.files} />
          <Row
            label="Lines"
            value={`+${changes.additions} −${changes.deletions}`}
          />
        </Section>
      )}

      {usage.total_tokens > 0 && (
        <Section title="Token usage">
          <Row label="Prompt" value={usage.prompt_tokens.toLocaleString()} />
          <Row
            label="Completion"
            value={usage.completion_tokens.toLocaleString()}
          />
          <Row label="Total" value={usage.total_tokens.toLocaleString()} />
          {usage.cost_usd > 0 && (
            <Row label="Cost" value={`$${usage.cost_usd.toFixed(4)}`} />
          )}
        </Section>
      )}

      {context.workspace_sketch && (
        <Section title="Workspace sketch">
          <Note text={context.workspace_sketch.text} />
        </Section>
      )}

      {context.condensation && (
        <Section title="Condensed history">
          <Note text={context.condensation.text} />
        </Section>
      )}

      <Extensions conversationId={conversationId} />

      {context.last_error && (
        <Section title="Last error">
          <p className="mb-2 text-sm">{context.last_error.message}</p>
          <FailureReference
            conversationId={conversationId}
            traceId={context.last_error.trace_id}
          />
        </Section>
      )}
    </div>
  );
}
