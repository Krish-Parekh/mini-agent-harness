"use client";

import { Fragment, useMemo } from "react";
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
  isFanoutWorker,
  isMessage,
  isObservation,
} from "@/lib/events";
import {
  type FanoutWorkerState,
  buildFanoutWorkerMap,
} from "@/lib/fanout-workers";
import { ScrollablePreview, type ToolView, toolView } from "@/lib/tool-views";
import { formatDuration, formatElapsed, useElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useConversation } from "@/components/ai-elements/conversation";
import {
  Message,
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

function FanoutWorkersPanel({
  workers,
  live,
}: {
  workers: FanoutWorkerState[];
  live: boolean;
}) {
  if (workers.length === 0) return null;
  const done = workers.filter((w) => w.status === "done").length;
  const header = live
    ? `Spawning ${workers.length} read-only agent${workers.length === 1 ? "" : "s"}…`
    : `${done}/${workers.length} agent${workers.length === 1 ? "" : "s"} completed`;

  return (
    <div className="mt-2 space-y-2.5 rounded-lg border border-border/60 bg-muted/20 p-3">
      <p className="text-xs font-medium text-muted-foreground">{header}</p>
      <ul className="space-y-2">
        {workers.map((worker) => (
          <li key={worker.index} className="flex items-start gap-2.5">
            <FanoutWorkerGlyph status={worker.status} />
            <div className="min-w-0 space-y-0.5">
              <p className="text-sm font-medium leading-snug">{worker.title}</p>
              {worker.activity && (
                <p className="text-muted-foreground text-xs leading-relaxed">
                  {worker.activity}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FanoutWorkerGlyph({ status }: { status: FanoutWorkerState["status"] }) {
  if (status === "done") {
    return (
      <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-500" />
    );
  }
  if (status === "error") {
    return <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-destructive" />;
  }
  if (status === "running") {
    return <Spinner className="mt-0.5 size-4 shrink-0 text-amber-500" />;
  }
  return (
    <CircleIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground/40" />
  );
}

function ChainStep({
  action,
  obs,
  isPending,
  live,
  fanoutWorkers,
  onApprove,
  onReject,
  onSelectFile,
}: {
  action: ActionEvent;
  obs?: AgentEvent;
  isPending: boolean;
  live: boolean;
  fanoutWorkers?: FanoutWorkerState[];
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
      {action.tool_name === "fanout" && fanoutWorkers && fanoutWorkers.length > 0 && (
        <FanoutWorkersPanel
          workers={fanoutWorkers}
          live={running || (live && !obs)}
        />
      )}
    </ChainOfThoughtStep>
  );
}

function ActionChain({
  actions,
  observationByCall,
  fanoutWorkersByCall,
  pendingId,
  live,
  onApprove,
  onReject,
  onSelectFile,
}: {
  actions: ActionEvent[];
  observationByCall: Map<string, AgentEvent>;
  fanoutWorkersByCall: Map<string, FanoutWorkerState[]>;
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
  const label = `${actions.length} tool ${actions.length === 1 ? "call" : "calls"}`;

  return (
    <ChainOfThought defaultOpen>
      <ChainOfThoughtHeader>
        {active ? (
          <span className="flex items-center gap-2">
            <DotmSquare1 size={14} dotSize={2} muted />
            {label}
          </span>
        ) : (
          label
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
            fanoutWorkers={
              a.tool_name === "fanout" && a.tool_call_id
                ? fanoutWorkersByCall.get(a.tool_call_id)
                : undefined
            }
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

type Group =
  | { kind: "message"; event: MessageEvent }
  | { kind: "error"; event: AgentEvent }
  | { kind: "plan"; event: ActionEvent }
  | { kind: "questions"; event: ActionEvent }
  | { kind: "actions"; actions: ActionEvent[] };

function finishText(action: ActionEvent, obs?: AgentEvent): string | null {
  if (obs?.error) return null;
  const fromArgs = String(action.arguments?.message ?? "").trim();
  const fromObs = (obs?.content ?? "").trim();
  return fromArgs || fromObs || null;
}

/** Tool-only turns store the answer in `finish` or `fanout`, not a message event. */
function synthesizeToolResponse(
  actions: ActionEvent[],
  observationByCall: Map<string, AgentEvent>,
): string | null {
  for (let i = actions.length - 1; i >= 0; i--) {
    const action = actions[i];
    const obs = action.tool_call_id
      ? observationByCall.get(action.tool_call_id)
      : undefined;
    if (action.tool_name === "finish") {
      const text = finishText(action, obs);
      if (text) return text;
    }
  }
  for (let i = actions.length - 1; i >= 0; i--) {
    const action = actions[i];
    if (action.tool_name !== "fanout") continue;
    const obs = action.tool_call_id
      ? observationByCall.get(action.tool_call_id)
      : undefined;
    if (obs?.content?.trim() && !obs.error) return obs.content.trim();
  }
  return null;
}

function hasLaterAssistantReply(groups: Group[], afterIndex: number): boolean {
  for (let i = afterIndex + 1; i < groups.length; i++) {
    const group = groups[i];
    if (group.kind === "message") {
      if (group.event.role === "user") return false;
      if (group.event.role === "assistant" && group.event.text?.trim()) {
        return true;
      }
    }
  }
  return false;
}

function ToolResponseRow({ text }: { text: string }) {
  return (
    <Message from="assistant">
      <MessageContent>
        <MessageResponse>{text}</MessageResponse>
      </MessageContent>
    </Message>
  );
}

function MessageRow({
  ev,
  isLatestUserTurn,
}: {
  ev: MessageEvent;
  isLatestUserTurn?: boolean;
}) {
  // Assistant turns can carry tool calls without visible text; skip the bubble.
  if (ev.role === "assistant" && !(ev.text ?? "").trim()) return null;

  if (ev.role === "user") {
    return (
      <Message from="user" {...(isLatestUserTurn ? { "data-user-turn": "" } : {})}>
        <MessageContent>{ev.text}</MessageContent>
      </Message>
    );
  }

  return (
    <Message from="assistant">
      <MessageContent>
        <MessageResponse>{ev.text ?? ""}</MessageResponse>
      </MessageContent>
    </Message>
  );
}

function hasAssistantReplyAfterLastUser(groups: Group[]): boolean {
  let lastUserIdx = -1;
  for (let i = groups.length - 1; i >= 0; i--) {
    const group = groups[i];
    if (group.kind === "message" && group.event.role === "user") {
      lastUserIdx = i;
      break;
    }
  }
  if (lastUserIdx === -1) return false;
  for (let i = lastUserIdx + 1; i < groups.length; i++) {
    const group = groups[i];
    if (
      group.kind === "message" &&
      group.event.role === "assistant" &&
      (group.event.text ?? "").trim()
    ) {
      return true;
    }
  }
  return false;
}

function AssistantStreamingRow() {
  return (
    <Message from="assistant" className="min-h-0 flex-1">
      <MessageContent className="w-full min-h-32">
        <ThinkingIndicator label="Working…" />
      </MessageContent>
    </Message>
  );
}

function groupEvents(events: AgentEvent[]): Group[] {
  const groups: Group[] = [];
  let chain: ActionEvent[] | null = null;
  for (const ev of events) {
    if (isObservation(ev)) continue;
    if (isFanoutWorker(ev)) continue;
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
    } else if (isMessage(ev)) {
      chain = null;
      groups.push({ kind: "message", event: ev });
    }
  }
  return groups;
}

export const OPTIMISTIC_USER_ID = "optimistic-user";

function withOptimisticUser(
  events: AgentEvent[],
  text: string | null | undefined,
): AgentEvent[] {
  if (!text?.trim()) return events;
  const lastUser = [...events]
    .reverse()
    .find((e) => isMessage(e) && e.role === "user");
  if (lastUser?.text === text) return events;
  return [
    ...events,
    {
      id: OPTIMISTIC_USER_ID,
      timestamp: Date.now() / 1000,
      source: "user",
      kind: "message",
      role: "user",
      text,
    },
  ];
}

export type ConversationTimelineProps = {
  events: AgentEvent[];
  optimisticUserText?: string | null;
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
  optimisticUserText,
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
  const groups = useMemo(
    () => groupEvents(withOptimisticUser(events, optimisticUserText)),
    [events, optimisticUserText],
  );
  const fanoutWorkersByCall = useMemo(
    () => buildFanoutWorkerMap(events),
    [events],
  );
  const latestUserId = useMemo(() => {
    for (let i = groups.length - 1; i >= 0; i--) {
      const group = groups[i];
      if (group.kind === "message" && group.event.role === "user") {
        return group.event.id;
      }
    }
    return undefined;
  }, [groups]);
  const live = status === "running" || status === "waiting_for_confirmation";
  const hasActiveToolWork =
    live &&
    events.some(
      (e) =>
        isAction(e) &&
        e.tool_call_id &&
        !observationByCall.has(e.tool_call_id),
    );
  const showAssistantStreaming =
    status === "running" &&
    !hasActiveToolWork &&
    !hasAssistantReplyAfterLastUser(groups);

  const lastUserIdx = useMemo(() => {
    for (let i = groups.length - 1; i >= 0; i--) {
      const group = groups[i];
      if (group.kind === "message" && group.event.role === "user") return i;
    }
    return -1;
  }, [groups]);

  const { viewportHeight } = useConversation();

  const renderGroup = (group: Group, i: number) => {
    if (group.kind === "actions") {
      const toolResponse = synthesizeToolResponse(
        group.actions,
        observationByCall,
      );
      const showToolResponse =
        toolResponse && !hasLaterAssistantReply(groups, i);
      return (
        <Fragment key={group.actions[0]?.id ?? i}>
          <ActionChain
            actions={group.actions}
            observationByCall={observationByCall}
            fanoutWorkersByCall={fanoutWorkersByCall}
            pendingId={pendingId}
            live={live}
            onApprove={onApprove}
            onReject={onReject}
            onSelectFile={onSelectFile}
          />
          {showToolResponse && <ToolResponseRow text={toolResponse} />}
        </Fragment>
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
    return (
      <MessageRow
        key={group.event.id}
        ev={group.event}
        isLatestUserTurn={
          group.event.role === "user" && group.event.id === latestUserId
        }
      />
    );
  };

  return (
    <>
      {groups.map((group, i) => {
        if (lastUserIdx >= 0 && i >= lastUserIdx) return null;
        return renderGroup(group, i);
      })}
      {lastUserIdx >= 0 && groups[lastUserIdx]?.kind === "message" && (
        <div
          data-active-turn
          className="flex flex-col gap-6"
          style={
            viewportHeight > 0 ? { minHeight: viewportHeight } : undefined
          }
        >
          <MessageRow
            ev={(groups[lastUserIdx] as { kind: "message"; event: MessageEvent }).event}
            isLatestUserTurn
          />
          {groups.slice(lastUserIdx + 1).map((group, j) =>
            renderGroup(group, lastUserIdx + 1 + j),
          )}
          {showAssistantStreaming && <AssistantStreamingRow />}
        </div>
      )}
    </>
  );
}
