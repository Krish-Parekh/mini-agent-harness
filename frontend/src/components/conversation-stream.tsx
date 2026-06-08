"use client";

import type { AgentEvent } from "@/lib/api";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { CopyIcon } from "lucide-react";
import { DiffViewer } from "@/components/assistant-ui/diff-viewer";
import {
  Confirmation,
  ConfirmationActions,
  ConfirmationAction,
  ConfirmationTitle,
} from "@/components/ai-elements/confirmation";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";

type FileChange = { path: string; oldContent: string; newContent: string };

/** A `file_edit` action we can render as a before/after diff. `view` (read-only)
 * and every other tool return null and fall back to the Tool component. */
function fileChange(ev: AgentEvent): FileChange | null {
  if (ev.kind !== "action" || ev.tool_name !== "file_edit") return null;
  const a = (ev.arguments ?? {}) as Record<string, unknown>;
  const path = String(a.path ?? "file");
  if (a.command === "create") {
    return { path, oldContent: "", newContent: String(a.content ?? "") };
  }
  if (a.command === "str_replace") {
    return {
      path,
      oldContent: String(a.old_str ?? ""),
      newContent: String(a.new_str ?? ""),
    };
  }
  return null;
}

/** Map our (action, observation) pair onto the ai-SDK tool lifecycle states the
 * Tool header understands. */
function toolState(pending: boolean, observation?: AgentEvent) {
  if (pending) return "approval-requested" as const;
  if (!observation) return "input-available" as const; // running, no result yet
  return observation.error
    ? ("output-error" as const)
    : ("output-available" as const);
}

function ToolCall({
  ev,
  observation,
  pending,
}: {
  ev: AgentEvent;
  observation?: AgentEvent;
  pending: boolean;
}) {
  const content = observation?.content ?? "";
  return (
    <Tool defaultOpen={pending || observation?.error}>
      <ToolHeader
        type="dynamic-tool"
        toolName={ev.tool_name ?? "tool"}
        state={toolState(pending, observation)}
      />
      <ToolContent>
        <ToolInput input={ev.arguments ?? {}} />
        <ToolOutput
          output={observation && !observation.error ? content : undefined}
          errorText={observation?.error ? content : undefined}
        />
      </ToolContent>
    </Tool>
  );
}

/** The body of an action: a diff for file edits, otherwise the Tool component.
 * Shared by the auto-applied path and the confirmation gate so the user sees
 * exactly the same thing whether or not approval is required. */
function ActionBody({
  ev,
  observation,
  pending = false,
}: {
  ev: AgentEvent;
  observation?: AgentEvent;
  pending?: boolean;
}) {
  const change = fileChange(ev);
  if (change) {
    return (
      <>
        <DiffViewer
          oldFile={{ content: change.oldContent, name: change.path }}
          newFile={{ content: change.newContent, name: change.path }}
          viewMode="unified"
        />
        {observation?.error && (
          <pre className="border-destructive/40 text-destructive mt-1 overflow-x-auto rounded-md border px-3 py-2 text-xs">
            {(observation.content ?? "").slice(0, 4000)}
          </pre>
        )}
      </>
    );
  }
  return <ToolCall ev={ev} observation={observation} pending={pending} />;
}

export type EventRowProps = {
  ev: AgentEvent;
  observation?: AgentEvent;
  pending?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
};

export function EventRow({
  ev,
  observation,
  pending,
  onApprove,
  onReject,
}: EventRowProps) {
  if (ev.kind === "message") {
    if (ev.role === "system") {
      return (
        <p className="text-muted-foreground text-center text-xs">{ev.text}</p>
      );
    }
    if (ev.role === "user") {
      return (
        <Message from="user">
          <MessageContent>{ev.text}</MessageContent>
        </Message>
      );
    }
    return (
      <Message from="assistant">
        <MessageContent>
          <MessageResponse>{ev.text ?? ""}</MessageResponse>
        </MessageContent>
        <MessageActions className="opacity-0 transition-opacity group-hover:opacity-100">
          <MessageAction
            label="Copy"
            onClick={() => navigator.clipboard.writeText(ev.text ?? "")}
          >
            <CopyIcon className="size-3" />
          </MessageAction>
        </MessageActions>
      </Message>
    );
  }

  if (ev.kind === "error") {
    return <p className="text-destructive text-sm">⚠ {ev.message}</p>;
  }

  // Observations are folded into their action's Tool (or diff), so they don't
  // render a row of their own.
  if (ev.kind === "observation") return null;

  if (ev.kind === "action") {
    if (pending) {
      return (
        <Confirmation
          state="approval-requested"
          approval={{ id: ev.tool_call_id ?? ev.id }}
        >
          <ConfirmationTitle>
            Approve <span className="font-medium">{ev.tool_name}</span>?
          </ConfirmationTitle>
          <ActionBody ev={ev} observation={observation} pending />
          <ConfirmationActions>
            <ConfirmationAction variant="outline" onClick={onReject}>
              Reject
            </ConfirmationAction>
            <ConfirmationAction onClick={onApprove}>Approve</ConfirmationAction>
          </ConfirmationActions>
        </Confirmation>
      );
    }
    return <ActionBody ev={ev} observation={observation} />;
  }

  return null;
}
