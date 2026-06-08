"use client";

import { useMemo } from "react";
import type { AgentEvent } from "@/lib/api";
import {
  type ActionEvent,
  type MessageEvent,
  isAction,
  isErrorEvent,
  isObservation,
} from "@/lib/events";
import { type ToolView, toolView } from "@/lib/tool-views";
import { cn } from "@/lib/utils";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { DotmSquare1 } from "@/components/ui/dotm-square-1";
import { ConfirmationAction } from "@/components/ai-elements/confirmation";
import { DiffViewer } from "@/components/assistant-ui/diff-viewer";
import { CircleAlertIcon, CopyIcon } from "lucide-react";

function ApprovalDetail({ view }: { view: ToolView }) {
  if (view.fileChange) {
    return (
      <DiffViewer
        oldFile={{
          content: view.fileChange.oldContent,
          name: view.fileChange.path,
        }}
        newFile={{
          content: view.fileChange.newContent,
          name: view.fileChange.path,
        }}
        viewMode="unified"
      />
    );
  }
  return <>{view.preview ?? null}</>;
}

function StepLabel({
  view,
  error,
  onSelectFile,
}: {
  view: ToolView;
  error?: boolean;
  onSelectFile?: (path: string) => void;
}) {
  return (
    <span className="flex items-center gap-2">
      <span className={cn("font-medium", error && "text-destructive")}>
        {view.verb}
      </span>
      {view.target &&
        (view.filePath && onSelectFile ? (
          <button
            type="button"
            onClick={() => onSelectFile(view.filePath as string)}
            className="truncate font-mono text-muted-foreground text-xs hover:underline"
          >
            {view.target}
          </button>
        ) : (
          <span className="truncate font-mono text-muted-foreground text-xs">
            {view.target}
          </span>
        ))}
    </span>
  );
}

function ActionChain({
  actions,
  observationByCall,
  pendingId,
  onApprove,
  onReject,
  onSelectFile,
}: {
  actions: ActionEvent[];
  observationByCall: Map<string, AgentEvent>;
  pendingId?: string;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
}) {
  const obsFor = (a: ActionEvent) =>
    a.tool_call_id ? observationByCall.get(a.tool_call_id) : undefined;
  const active = actions.some((a) => !obsFor(a));

  return (
    <ChainOfThought defaultOpen>
      <ChainOfThoughtHeader>
        {active ? (
          <span className="flex items-center gap-2">
            <DotmSquare1 size={14} dotSize={2} muted />
            Working…
          </span>
        ) : (
          `${actions.length} tool ${actions.length === 1 ? "call" : "calls"}`
        )}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {actions.map((a) => {
          const obs = obsFor(a);
          const view = toolView(a);
          const isPending = pendingId != null && a.id === pendingId;
          const running = !obs && !isPending;
          return (
            <ChainOfThoughtStep
              key={a.id}
              icon={obs?.error ? CircleAlertIcon : view.icon}
              status={running || isPending ? "active" : "complete"}
              label={
                <StepLabel
                  view={view}
                  error={obs?.error}
                  onSelectFile={onSelectFile}
                />
              }
            >
              {isPending && (
                <div className="space-y-2">
                  <ApprovalDetail view={view} />
                  <div className="flex items-center justify-end gap-2">
                    <ConfirmationAction variant="outline" onClick={onReject}>
                      Reject
                    </ConfirmationAction>
                    <ConfirmationAction onClick={onApprove}>
                      Approve
                    </ConfirmationAction>
                  </div>
                </div>
              )}
              {obs?.error && (
                <p className="text-destructive text-xs">
                  {(obs.content ?? "").slice(0, 300)}
                </p>
              )}
            </ChainOfThoughtStep>
          );
        })}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}

function MessageRow({ ev }: { ev: MessageEvent }) {
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

type Group =
  | { kind: "message"; event: MessageEvent }
  | { kind: "error"; event: AgentEvent }
  | { kind: "actions"; actions: ActionEvent[] };

function groupEvents(events: AgentEvent[]): Group[] {
  const groups: Group[] = [];
  let chain: ActionEvent[] | null = null;
  for (const ev of events) {
    if (isObservation(ev)) continue;
    if (isAction(ev)) {
      if (!chain) {
        chain = [];
        groups.push({ kind: "actions", actions: chain });
      }
      chain.push(ev);
    } else if (isErrorEvent(ev)) {
      chain = null;
      groups.push({ kind: "error", event: ev });
    } else {
      chain = null;
      groups.push({ kind: "message", event: ev as MessageEvent });
    }
  }
  return groups;
}

export type ConversationTimelineProps = {
  events: AgentEvent[];
  observationByCall: Map<string, AgentEvent>;
  pendingId?: string;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
};

export function ConversationTimeline({
  events,
  observationByCall,
  pendingId,
  onApprove,
  onReject,
  onSelectFile,
}: ConversationTimelineProps) {
  const groups = useMemo(() => groupEvents(events), [events]);

  return (
    <>
      {groups.map((group, i) => {
        if (group.kind === "actions") {
          return (
            <ActionChain
              key={group.actions[0]?.id ?? i}
              actions={group.actions}
              observationByCall={observationByCall}
              pendingId={pendingId}
              onApprove={onApprove}
              onReject={onReject}
              onSelectFile={onSelectFile}
            />
          );
        }
        if (group.kind === "error") {
          return (
            <p key={group.event.id} className="text-destructive text-sm">
              ⚠ {group.event.message}
            </p>
          );
        }
        return <MessageRow key={group.event.id} ev={group.event} />;
      })}
    </>
  );
}
