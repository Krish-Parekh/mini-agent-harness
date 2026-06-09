"use client";

import { useMemo } from "react";
import type { AgentEvent, ConversationStatus } from "@/lib/api";
import {
  type ActionEvent,
  type MessageEvent,
  isAction,
  isErrorEvent,
  isObservation,
} from "@/lib/events";
import { type ToolView, toolView } from "@/lib/tool-views";
import { formatDuration, formatElapsed, useElapsed } from "@/lib/time";
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

// Timing label for a step. Bash measures its own wall-clock (`duration_ms`);
// other tools fall back to the gap between the action and its observation. While
// a step is still running we tick a live elapsed counter, since no observation
// has arrived to read a final duration from.
function stepTiming(
  action: ActionEvent,
  obs: AgentEvent | undefined,
  running: boolean,
  elapsedMs: number,
): string | undefined {
  if (action.tool_name !== "bash") return undefined;
  if (running) return `Running ${formatElapsed(elapsedMs)}`;
  if (!obs) return undefined;
  const ms =
    obs.duration_ms != null
      ? obs.duration_ms
      : (obs.timestamp - action.timestamp) * 1000;
  return formatDuration(ms);
}

function ChainStep({
  action,
  obs,
  isPending,
  live,
  onApprove,
  onReject,
  onSelectFile,
}: {
  action: ActionEvent;
  obs?: AgentEvent;
  isPending: boolean;
  live: boolean;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
}) {
  const view = toolView(action);
  // An action with no observation is only genuinely "running" while the
  // conversation is still live; once it's idle/finished/errored, such an action
  // was interrupted and must not keep spinning forever.
  const unresolved = !obs && !isPending;
  const running = unresolved && live;
  const orphaned = unresolved && !live;
  const elapsed = useElapsed(running ? action.timestamp * 1000 : null, running);
  const timing = stepTiming(action, obs, running, elapsed);
  const isError = obs?.error || orphaned;

  return (
    <ChainOfThoughtStep
      icon={isError ? CircleAlertIcon : view.icon}
      status={running || isPending ? "active" : "complete"}
      label={
        <StepLabel view={view} error={isError} onSelectFile={onSelectFile} />
      }
      description={orphaned ? "Interrupted" : timing}
    >
      {isPending && (
        <div className="space-y-2">
          <ApprovalDetail view={view} />
          <div className="flex items-center justify-end gap-2">
            <ConfirmationAction variant="outline" onClick={onReject}>
              Reject
            </ConfirmationAction>
            <ConfirmationAction onClick={onApprove}>Approve</ConfirmationAction>
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
}

function ActionChain({
  actions,
  observationByCall,
  pendingId,
  live,
  onApprove,
  onReject,
  onSelectFile,
}: {
  actions: ActionEvent[];
  observationByCall: Map<string, AgentEvent>;
  pendingId?: string;
  live: boolean;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
}) {
  const obsFor = (a: ActionEvent) =>
    a.tool_call_id ? observationByCall.get(a.tool_call_id) : undefined;
  // Only show the live "Working…" header while the conversation is actually
  // running; a leftover unobserved action on a stopped chat isn't working.
  const active = live && actions.some((a) => !obsFor(a));

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
        {actions.map((a) => (
          <ChainStep
            key={a.id}
            action={a}
            obs={obsFor(a)}
            isPending={pendingId != null && a.id === pendingId}
            live={live}
            onApprove={onApprove}
            onReject={onReject}
            onSelectFile={onSelectFile}
          />
        ))}
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}

// Standalone pulse shown while the agent is running but isn't mid-tool-call.
// The action chain renders its own "Working…" header, so this only fills the
// gaps: right after the user sends (before the first event), and between an
// assistant message / finished chain and the next step.
export function ThinkingIndicator({ label = "Working…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-1 text-muted-foreground text-sm">
      <DotmSquare1 size={14} dotSize={2} muted />
      <span>{label}</span>
    </div>
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
  status: ConversationStatus;
  pendingId?: string;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
};

export function ConversationTimeline({
  events,
  observationByCall,
  status,
  pendingId,
  onApprove,
  onReject,
  onSelectFile,
}: ConversationTimelineProps) {
  const groups = useMemo(() => groupEvents(events), [events]);
  const live = status === "running" || status === "waiting_for_confirmation";

  // The trailing tool chain already shows its own animated header while it has
  // an unresolved action, so suppress the standalone pulse in that case to avoid
  // two spinners. Otherwise, show the pulse whenever the agent is running.
  const lastGroup = groups[groups.length - 1];
  const trailingChainActive =
    lastGroup?.kind === "actions" &&
    lastGroup.actions.some(
      (a) => !(a.tool_call_id && observationByCall.has(a.tool_call_id)),
    );
  const thinking =
    status === "running" && groups.length > 0 && !trailingChainActive;

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
              live={live}
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
      {thinking && <ThinkingIndicator />}
    </>
  );
}
