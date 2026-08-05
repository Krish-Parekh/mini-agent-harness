"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { type ConversationContext } from "@/lib/api";
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
        {context.workspace_dir && (
          <Row
            label="Worktree"
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
