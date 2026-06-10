"use client";

import { useMemo, useState } from "react";
import type {
  AgentEvent,
  ConversationStatus,
  PlanStep,
  StepStatus,
} from "@/lib/api";
import {
  type ActionEvent,
  type MessageEvent,
  isAction,
  isErrorEvent,
  isObservation,
} from "@/lib/events";
import { ScrollablePreview, type ToolView, toolView } from "@/lib/tool-views";
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
import {
  Plan,
  PlanAction,
  PlanContent,
  PlanDescription,
  PlanFooter,
  PlanHeader,
  PlanTitle,
  PlanTrigger,
} from "@/components/ai-elements/plan";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleIcon,
  ClipboardListIcon,
  HammerIcon,
} from "lucide-react";
import { HugeiconsIcon } from "@hugeicons/react";
import { CopyCheckIcon, CopyIcon } from "@hugeicons/core-free-icons";

function ApprovalDetail({ view }: { view: ToolView }) {
  if (view.fileChange) {
    const isSnippet = view.fileChange.kind === "snippet";
    return (
      <div className="space-y-1.5">
        {isSnippet && (
          <p className="text-muted-foreground text-xs">
            Replacing matched snippet in{" "}
            <span className="font-mono">{view.fileChange.path}</span>
          </p>
        )}
        <ScrollablePreview>
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
        </ScrollablePreview>
      </div>
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
        <ScrollablePreview>
          <pre className="whitespace-pre-wrap break-words text-destructive text-xs">
            {obs.content ?? ""}
          </pre>
        </ScrollablePreview>
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

function StepGlyph({ status }: { status: StepStatus }) {
  if (status === "done")
    return <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-500" />;
  if (status === "in_progress")
    return <Spinner className="mt-0.5 size-4 shrink-0 text-amber-500" />;
  return (
    <CircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground/40" />
  );
}

function PlanStepRow({ step }: { step: PlanStep }) {
  return (
    <div className="flex items-start gap-2.5">
      <StepGlyph status={step.status} />
      <div className="min-w-0 space-y-0.5">
        <p
          className={cn(
            "text-sm font-medium",
            step.status === "done" && "text-muted-foreground line-through",
          )}
        >
          {step.title}
        </p>
        {step.description && (
          <p className="text-muted-foreground text-xs">{step.description}</p>
        )}
        {step.files?.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {step.files.map((f) => (
              <span
                key={f}
                className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
              >
                {f}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PlanCard({
  ev,
  liveSteps,
  isPending,
  onBuild,
}: {
  ev: ActionEvent;
  liveSteps?: PlanStep[];
  isPending?: boolean;
  onBuild?: () => void;
}) {
  const steps = liveSteps ?? ((ev.arguments?.steps as PlanStep[]) ?? []);
  // Plans presented before the structured schema carry a markdown blob.
  const legacyPlan =
    steps.length === 0 ? String((ev.arguments?.plan as string) ?? "") : "";
  return (
    <Plan defaultOpen>
      <PlanHeader>
        <div className="space-y-1">
          <PlanTitle>{String(ev.arguments?.title ?? "Plan")}</PlanTitle>
          <PlanDescription>
            {isPending
              ? "Review, then build — or reply to refine"
              : "Send a message to approve or refine"}
          </PlanDescription>
        </div>
        <PlanAction>
          <PlanTrigger />
        </PlanAction>
      </PlanHeader>
      <PlanContent>
        {legacyPlan ? (
          <MessageResponse>{legacyPlan}</MessageResponse>
        ) : (
          <div className="space-y-3">
            {steps.map((step, i) => (
              <PlanStepRow key={i} step={step} />
            ))}
          </div>
        )}
      </PlanContent>
      {isPending && onBuild && (
        <PlanFooter className="justify-end">
          <Button size="sm" onClick={onBuild}>
            <HammerIcon className="size-4" />
            Build
          </Button>
        </PlanFooter>
      )}
    </Plan>
  );
}

function QuestionsSummary({ ev }: { ev: ActionEvent }) {
  const questions = (ev.arguments?.questions as { question: string }[]) ?? [];
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
        <ClipboardListIcon className="size-4 text-muted-foreground" />
        Asked you {questions.length === 1 ? "a question" : `${questions.length} questions`}
      </div>
      <ul className="space-y-1 text-muted-foreground text-sm">
        {questions.map((q, i) => (
          <li key={i}>• {q.question}</li>
        ))}
      </ul>
    </div>
  );
}

export function ThinkingIndicator({ label = "Working…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-1 text-muted-foreground text-sm">
      <DotmSquare1 size={16} dotSize={2} muted />
      <span>{label}</span>
    </div>
  );
}

function MessageRow({ ev }: { ev: MessageEvent }) {
  const [copied, setCopied] = useState(false);

  if (ev.role === "user") {
    return (
      <Message from="user" data-turn-id={ev.id}>
        <MessageContent>{ev.text}</MessageContent>
      </Message>
    );
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(ev.text ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Message from="assistant">
      <MessageContent>
        <MessageResponse>{ev.text ?? ""}</MessageResponse>
      </MessageContent>
      <MessageActions className="opacity-0 transition-opacity group-hover:opacity-100">
        <MessageAction label={copied ? "Copied" : "Copy"} onClick={handleCopy}>
          <span className="relative inline-flex size-3 items-center justify-center">
            <HugeiconsIcon
              icon={CopyIcon}
              size={42}
              className={cn(
                "absolute size-3 transition-all duration-200 ease-out",
                copied
                  ? "scale-50 rotate-12 opacity-0"
                  : "scale-100 rotate-0 opacity-100",
              )}
            />
            <HugeiconsIcon
              icon={CopyCheckIcon}
              size={42}
              className={cn(
                "absolute size-3 transition-all duration-200 ease-out",
                copied
                  ? "scale-100 rotate-0 opacity-100"
                  : "scale-50 -rotate-12 opacity-0",
              )}
            />
          </span>
        </MessageAction>
      </MessageActions>
    </Message>
  );
}

type Group =
  | { kind: "message"; event: MessageEvent }
  | { kind: "error"; event: AgentEvent }
  | { kind: "plan"; event: ActionEvent }
  | { kind: "questions"; event: ActionEvent }
  | { kind: "actions"; actions: ActionEvent[] };

function groupEvents(events: AgentEvent[]): Group[] {
  const groups: Group[] = [];
  let chain: ActionEvent[] | null = null;
  for (const ev of events) {
    if (isObservation(ev)) continue;
    // System messages (e.g. the legacy "Workspace ready" banner) are noise in
    // the timeline; skip them so old persisted logs stop rendering them too.
    if (!isAction(ev) && !isErrorEvent(ev) && (ev as MessageEvent).role === "system")
      continue;
    // A presented plan is the turn's headline, not a tool-call detail — break
    // the chain and render it as its own card.
    if (isAction(ev) && ev.tool_name === "present_plan") {
      chain = null;
      groups.push({ kind: "plan", event: ev as ActionEvent });
    } else if (isAction(ev) && ev.tool_name === "ask_user") {
      chain = null;
      groups.push({ kind: "questions", event: ev as ActionEvent });
    } else if (isAction(ev)) {
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
  pendingQuestionId?: string;
  pendingPlanId?: string;
  livePlan?: { planId: string; steps: PlanStep[] };
  onApprove: () => void;
  onReject: () => void;
  onBuild?: () => void;
  onSelectFile?: (path: string) => void;
};

export function ConversationTimeline({
  events,
  observationByCall,
  status,
  pendingId,
  pendingQuestionId,
  pendingPlanId,
  livePlan,
  onApprove,
  onReject,
  onBuild,
  onSelectFile,
}: ConversationTimelineProps) {
  const groups = useMemo(() => groupEvents(events), [events]);
  const live = status === "running" || status === "waiting_for_confirmation";

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
        if (group.kind === "plan") {
          return (
            <PlanCard
              key={group.event.id}
              ev={group.event}
              liveSteps={
                group.event.id === livePlan?.planId ? livePlan.steps : undefined
              }
              isPending={group.event.id === pendingPlanId}
              onBuild={onBuild}
            />
          );
        }
        if (group.kind === "questions") {
          // The pending question is shown interactively above the composer;
          // skip it here so it isn't duplicated.
          if (group.event.id === pendingQuestionId) return null;
          return <QuestionsSummary key={group.event.id} ev={group.event} />;
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
