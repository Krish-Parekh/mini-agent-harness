"use client";

import { useMemo } from "react";
import type { AgentEvent } from "@/lib/api";
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
import type { LucideIcon } from "lucide-react";
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CopyIcon,
  FileIcon,
  FilePenIcon,
  FilePlusIcon,
  TerminalIcon,
} from "lucide-react";

type FileChange = { path: string; oldContent: string; newContent: string };

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

type ActionInfo = {
  icon: LucideIcon;
  verb: string;
  target?: string;
  path?: string;
};

function describeAction(ev: AgentEvent): ActionInfo {
  const a = (ev.arguments ?? {}) as Record<string, unknown>;
  if (ev.tool_name === "bash") {
    return { icon: TerminalIcon, verb: "Bash", target: String(a.command ?? "") };
  }
  if (ev.tool_name === "file_edit") {
    const path = String(a.path ?? "file");
    if (a.command === "view") return { icon: FileIcon, verb: "Read", target: path };
    if (a.command === "create")
      return { icon: FilePlusIcon, verb: "Create", target: path, path };
    return { icon: FilePenIcon, verb: "Update", target: path, path };
  }
  if (ev.tool_name === "finish") {
    return { icon: CircleCheckIcon, verb: "Finished" };
  }
  return { icon: FileIcon, verb: ev.tool_name ?? "Tool" };
}

function ApprovalDetail({ ev }: { ev: AgentEvent }) {
  const change = fileChange(ev);
  if (change) {
    return (
      <DiffViewer
        oldFile={{ content: change.oldContent, name: change.path }}
        newFile={{ content: change.newContent, name: change.path }}
        viewMode="unified"
      />
    );
  }
  if (ev.tool_name === "bash") {
    const command = String((ev.arguments ?? {}).command ?? "");
    return (
      <pre className="overflow-x-auto rounded-md bg-muted/50 px-3 py-2 font-mono text-xs">
        {command}
      </pre>
    );
  }
  return null;
}

function StepLabel({
  info,
  error,
  onSelectFile,
}: {
  info: ActionInfo;
  error?: boolean;
  onSelectFile?: (path: string) => void;
}) {
  return (
    <span className="flex items-center gap-2">
      <span className={cn("font-medium", error && "text-destructive")}>
        {info.verb}
      </span>
      {info.target &&
        (info.path && onSelectFile ? (
          <button
            type="button"
            onClick={() => onSelectFile(info.path as string)}
            className="truncate font-mono text-muted-foreground text-xs hover:underline"
          >
            {info.target}
          </button>
        ) : (
          <span className="truncate font-mono text-muted-foreground text-xs">
            {info.target}
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
  actions: AgentEvent[];
  observationByCall: Map<string, AgentEvent>;
  pendingId?: string;
  onApprove: () => void;
  onReject: () => void;
  onSelectFile?: (path: string) => void;
}) {
  const obsFor = (a: AgentEvent) =>
    a.tool_call_id ? observationByCall.get(a.tool_call_id) : undefined;
  const active = actions.some((a) => !obsFor(a));

  return (
    <ChainOfThought defaultOpen>
      <ChainOfThoughtHeader>
        {active ? (
          <span className="flex items-center gap-2">
            <DotmSquare1 size={16} muted />
            Working…
          </span>
        ) : (
          `${actions.length} tool ${actions.length === 1 ? "call" : "calls"}`
        )}
      </ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        {actions.map((a) => {
          const obs = obsFor(a);
          const info = describeAction(a);
          const isPending = pendingId != null && a.id === pendingId;
          const running = !obs && !isPending;
          return (
            <ChainOfThoughtStep
              key={a.id}
              icon={obs?.error ? CircleAlertIcon : info.icon}
              status={running || isPending ? "active" : "complete"}
              label={
                <StepLabel
                  info={info}
                  error={obs?.error}
                  onSelectFile={onSelectFile}
                />
              }
            >
              {isPending && (
                <div className="space-y-2">
                  <ApprovalDetail ev={a} />
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

function MessageRow({ ev }: { ev: AgentEvent }) {
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
  | { kind: "event"; event: AgentEvent }
  | { kind: "actions"; actions: AgentEvent[] };

function groupEvents(events: AgentEvent[]): Group[] {
  const groups: Group[] = [];
  let chain: AgentEvent[] | null = null;
  for (const ev of events) {
    if (ev.kind === "observation") continue;
    if (ev.kind === "action") {
      if (!chain) {
        chain = [];
        groups.push({ kind: "actions", actions: chain });
      }
      chain.push(ev);
    } else {
      chain = null;
      groups.push({ kind: "event", event: ev });
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
        if (group.event.kind === "error") {
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
