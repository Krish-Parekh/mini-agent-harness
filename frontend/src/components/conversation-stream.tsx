"use client";

import { Fragment, memo, useMemo, useState } from "react";
import { CircleAlertIcon, ClipboardListIcon, HammerIcon, Undo2Icon } from "lucide-react";
import type { AgentEvent, ConversationStatus, PlanStep, StepStatus } from "@/lib/api";
import { failureMessage } from "@/lib/errors";
import {
  type ActionEvent,
  type ErrorEvent,
  type MessageEvent,
  eventKey,
  isAction,
  isErrorEvent,
  isFanoutWorker,
  isMessage,
  isObservation,
} from "@/lib/events";
import { type FanoutWorkerState, buildFanoutWorkerMap } from "@/lib/fanout-workers";
import {
  ScrollablePreview,
  type ToolView,
  diffStat,
  observationSources,
  toolObservationDetail,
  toolView,
} from "@/lib/tool-views";
import { formatDuration, formatElapsed, useElapsed } from "@/lib/time";
import { cn } from "@/lib/utils";
import { DiffViewer } from "@/components/bui/diff-viewer";
import { ApprovalCard } from "@/components/bui/approval-card";
import { Pill } from "@/components/bui/button";
import {
  AssistantMessage,
  type Source,
  UserBubble,
  uniqueSources,
} from "@/components/bui/chat-message";
import { LoadingState } from "@/components/bui/loading-state";
import { MessageAttachments } from "@/components/message-attachments";
import {
  type ProposedSkill,
  SkillProposalCard,
  type SkillProposalOutcome,
  SkillProposalSummary,
  skillReplyOutcome,
} from "@/components/bui/skill-proposal-card";
import { Markdown } from "@/components/bui/markdown";
import { TaskBadge, TaskList, TaskRow, type TaskStatus } from "@/components/bui/task-rows";
import { DiffChips, type DiffStat, ToolRow, ToolRun } from "@/components/bui/tool-chips";
import { ValuePill } from "@/components/bui/value-pill";

const viewCache = new WeakMap<ActionEvent, ToolView>();
const statCache = new WeakMap<ActionEvent, DiffStat | null>();

function viewFor(action: ActionEvent): ToolView {
  let view = viewCache.get(action);
  if (!view) {
    view = toolView(action);
    viewCache.set(action, view);
  }
  return view;
}

function statFor(action: ActionEvent): DiffStat | undefined {
  if (!statCache.has(action)) {
    const change = viewFor(action).fileChange;
    statCache.set(action, change ? diffStat(change) : null);
  }
  return statCache.get(action) ?? undefined;
}

function FileDiff({ view }: { view: ToolView }) {
  if (!view.fileChange) return null;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      {view.fileChange.kind === "snippet" && (
        <p className="text-[12px] text-ink-3">
          Replacing matched snippet in <span className="font-mono">{view.fileChange.path}</span>
        </p>
      )}
      <ScrollablePreview>
        <DiffViewer
          oldFile={{ content: view.fileChange.oldContent, name: view.fileChange.path }}
          newFile={{ content: view.fileChange.newContent, name: view.fileChange.path }}
          viewMode="unified"
        />
      </ScrollablePreview>
    </div>
  );
}

function PendingApproval({
  view,
  onApprove,
  onReject,
}: {
  view: ToolView;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <ApprovalCard
      footer={
        <>
          <span className="pl-0.5 text-[12.5px] text-ink-2">Approve this action?</span>
          <div className="-mr-0.5 flex items-center gap-1.5">
            <Pill variant="ghost" size="sm" onClick={onReject}>
              Reject
            </Pill>
            <Pill variant="primary" size="sm" onClick={onApprove}>
              Approve
            </Pill>
          </div>
        </>
      }
    >
      {view.fileChange ? <FileDiff view={view} /> : (view.preview ?? (
        <span className="font-mono text-[12px] text-ink-2">{view.target ?? view.verb}</span>
      ))}
    </ApprovalCard>
  );
}

function stepTiming(
  action: ActionEvent,
  obs: AgentEvent | undefined,
  running: boolean,
  elapsedMs: number,
): string | undefined {
  if (
    action.tool_name === "bash" ||
    action.tool_name === "web_search" ||
    action.tool_name === "fetch_url" ||
    action.tool_name === "find_skills"
  ) {
    if (running) return `Running ${formatElapsed(elapsedMs)}`;
    if (!obs) return undefined;
    const ms =
      obs.duration_ms != null ? obs.duration_ms : (obs.timestamp - action.timestamp) * 1000;
    return formatDuration(ms);
  }
  return undefined;
}

const WORKER_STATUS: Record<FanoutWorkerState["status"], TaskStatus> = {
  pending: "pending",
  running: "running",
  done: "done",
  error: "failed",
};

function FanoutWorkersPanel({ workers, live }: { workers: FanoutWorkerState[]; live: boolean }) {
  if (workers.length === 0) return null;
  const done = workers.filter((w) => w.status === "done").length;
  const header = live
    ? `Spawning ${workers.length} read-only agent${workers.length === 1 ? "" : "s"}…`
    : `${done}/${workers.length} agent${workers.length === 1 ? "" : "s"} completed`;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[12px] font-medium text-ink-2 tabular-nums">{header}</p>
      <ul className="flex flex-col gap-1.5">
        {workers.map((worker) => (
          <li key={worker.index} className="flex items-start gap-2">
            <span className="mt-px flex size-4 shrink-0 items-center justify-center">
              <TaskBadge compact status={WORKER_STATUS[worker.status]} />
            </span>
            <div className="min-w-0">
              <p className="text-[12.5px] leading-snug font-medium text-ink">{worker.title}</p>
              {worker.activity && (
                <p className="text-[12px] leading-relaxed text-ink-3">{worker.activity}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function tailText(text: string, max = 8000): string {
  return text.length > max ? `…${text.slice(-max)}` : text;
}

const ChainStep = memo(function ChainStep({
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
  const view = viewFor(action);
  const stat = statFor(action);
  const unresolved = !obs && !isPending;
  const running = unresolved && live;
  const orphaned = unresolved && !live;
  const elapsed = useElapsed(running ? action.timestamp * 1000 : null, running);
  const timing = stepTiming(action, obs, running, elapsed);
  const isError = !!obs?.error || orphaned;
  const observationDetail =
    obs && isObservation(obs) ? toolObservationDetail(action.tool_name, obs) : undefined;
  const output =
    action.tool_name === "bash" && obs && !obs.error && obs.content?.trim()
      ? tailText(obs.content.trim())
      : undefined;
  const hasWorkers = action.tool_name === "fanout" && !!fanoutWorkers && fanoutWorkers.length > 0;
  const workersLive = running || (live && !obs);

  const hasDetail =
    isPending ||
    !!obs?.error ||
    !!observationDetail ||
    !!view.fileChange ||
    !!view.preview ||
    !!output ||
    hasWorkers;
  const autoOpen = !!obs?.error || (running && !!view.preview) || (hasWorkers && workersLive);
  const [manual, setManual] = useState<boolean | null>(null);
  const open = isPending || (manual ?? autoOpen);

  const target = view.target;
  const isUrl = !!target && /^https?:\/\//.test(target);
  const filePath = view.filePath;

  return (
    <ToolRow
      icon={isError ? CircleAlertIcon : view.icon}
      label={action.tool_name === "finish" && obs?.error ? "Finish rejected" : view.verb}
      chip={target || undefined}
      chipMono={view.mono ?? false}
      onChipClick={filePath && onSelectFile ? () => onSelectFile(filePath) : undefined}
      chipHref={isUrl ? target : undefined}
      stat={stat && !obs?.error ? stat : undefined}
      meta={orphaned ? "Interrupted" : isPending ? "Needs approval" : timing}
      status={running || isPending ? "running" : isError ? "error" : "done"}
      open={open}
      onToggle={hasDetail && !isPending ? () => setManual(!open) : undefined}
    >
      {hasDetail ? (
        <>
          {isPending ? (
            <PendingApproval view={view} onApprove={onApprove} onReject={onReject} />
          ) : (
            <>
              {view.fileChange && <FileDiff view={view} />}
              {!view.fileChange && view.preview}
            </>
          )}
          {output && (
            <ScrollablePreview>
              <pre className="whitespace-pre-wrap break-words rounded-control bg-inset px-2.5 py-2 font-mono text-[11.5px] leading-[1.6] text-ink-2 shadow-hairline">
                {output}
              </pre>
            </ScrollablePreview>
          )}
          {obs?.error && (
            <ScrollablePreview>
              <pre className="whitespace-pre-wrap break-words rounded-control bg-red-tint px-2.5 py-2 font-mono text-[11.5px] leading-[1.6] text-red">
                {obs.content ?? ""}
              </pre>
            </ScrollablePreview>
          )}
          {observationDetail}
          {hasWorkers && fanoutWorkers && (
            <FanoutWorkersPanel workers={fanoutWorkers} live={workersLive} />
          )}
        </>
      ) : null}
    </ToolRow>
  );
});

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
  const active = live && actions.some((a) => !obsFor(a));
  const label = `${actions.length} tool ${actions.length === 1 ? "call" : "calls"}`;

  let lastObsAt = 0;
  let settled = true;
  const files = new Map<string, DiffStat>();
  for (const a of actions) {
    const obs = obsFor(a);
    if (!obs) {
      settled = false;
      continue;
    }
    lastObsAt = Math.max(lastObsAt, obs.timestamp);
    const change = viewFor(a).fileChange;
    const stat = statFor(a);
    if (change && stat && !obs.error) {
      const prev = files.get(change.path);
      files.set(change.path, prev ? { add: prev.add + stat.add, del: prev.del + stat.del } : stat);
    }
  }
  const startAt = actions[0]?.timestamp ?? 0;
  const meta =
    settled && lastObsAt > startAt ? formatDuration((lastObsAt - startAt) * 1000) : undefined;
  const diffFiles = active
    ? []
    : Array.from(files, ([path, stat]) => ({ path, stat }));

  return (
    <ToolRun
      label={label}
      meta={meta}
      live={active}
      footer={diffFiles.length > 0 ? <DiffChips files={diffFiles} onSelect={onSelectFile} /> : null}
    >
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
    </ToolRun>
  );
}

const STEP_STATUS: Record<StepStatus, TaskStatus> = {
  pending: "pending",
  in_progress: "running",
  done: "done",
};

function PlanStepRow({ step, index }: { step: PlanStep; index: number }) {
  const files = step.files ?? [];
  const hasDetail = !!step.description || files.length > 0;
  return (
    <TaskRow
      label={step.title}
      sub={step.description || undefined}
      amount={files.length > 0 ? `${files.length} file${files.length === 1 ? "" : "s"}` : undefined}
      status={STEP_STATUS[step.status] ?? "pending"}
      step={index + 1}
      strike={step.status === "done"}
      index={index}
    >
      {hasDetail ? (
        <>
          {step.description && (
            <p className="text-[12px] leading-relaxed text-ink-2">{step.description}</p>
          )}
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {files.map((f) => (
                <span
                  key={f}
                  className="inline-flex h-5.5 items-center rounded-chip bg-field px-1.5 font-mono text-[11px] text-ink-2 shadow-hairline"
                >
                  {f}
                </span>
              ))}
            </div>
          )}
        </>
      ) : null}
    </TaskRow>
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
  const [open, setOpen] = useState(true);
  const steps = liveSteps ?? ((ev.arguments?.steps as PlanStep[]) ?? []);
  const legacyPlan = steps.length === 0 ? String((ev.arguments?.plan as string) ?? "") : "";
  const done = steps.filter((s) => s.status === "done").length;
  const running = steps.some((s) => s.status === "in_progress");

  return (
    <div
      className="w-full overflow-hidden rounded-card bg-surface shadow-card"
      style={{ animation: "fade-up 380ms var(--ease-out-strong) both" }}
    >
      <div className="flex items-start justify-between gap-3 p-3">
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-ink">{String(ev.arguments?.title ?? "Plan")}</div>
          <div className="mt-0.5 text-[12.5px] text-ink-3">
            {isPending ? "Review, then build, or reply to refine" : "Send a message to approve or refine"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {steps.length > 0 && (
            <ValuePill tone={done === steps.length ? "green" : running ? "brand" : "neutral"}>
              {done}/{steps.length} done
            </ValuePill>
          )}
          <button
            type="button"
            aria-expanded={open}
            aria-label={open ? "Collapse plan" : "Expand plan"}
            onClick={() => setOpen((current) => !current)}
            className="inline-flex size-7 items-center justify-center rounded-control text-ink-3 transition-colors duration-100 hover:bg-hover hover:text-ink"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
              className="transition-transform duration-300"
              style={{ transform: open ? "rotate(180deg)" : "rotate(0)" }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        </div>
      </div>
      {open &&
        (legacyPlan ? (
          <div className="border-t border-line px-3 py-2.5 text-[14px] leading-relaxed text-ink">
            <Markdown>{legacyPlan}</Markdown>
          </div>
        ) : (
          <TaskList className="border-t border-line">
            {steps.map((step, i) => (
              <PlanStepRow key={i} step={step} index={i} />
            ))}
          </TaskList>
        ))}
      {isPending && onBuild && (
        <div className="flex justify-end border-t border-line p-2.5">
          <Pill variant="primary" size="sm" onClick={onBuild}>
            <HammerIcon className="size-3.5" />
            Build
          </Pill>
        </div>
      )}
    </div>
  );
}

function QuestionsSummary({ ev }: { ev: ActionEvent }) {
  const questions = (ev.arguments?.questions as { question: string }[]) ?? [];
  return (
    <div
      className="w-full rounded-card bg-surface p-3 shadow-card"
      style={{ animation: "fade-up 380ms var(--ease-out-strong) both" }}
    >
      <div className="flex items-center gap-2 text-[13px] font-medium text-ink">
        <ClipboardListIcon className="size-3.5 text-ink-3" />
        Asked you {questions.length === 1 ? "a question" : `${questions.length} questions`}
      </div>
      <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-[1.6rem] text-[13px] text-ink-2 marker:text-ink-3">
        {questions.map((q, i) => (
          <li key={i}>{q.question}</li>
        ))}
      </ul>
    </div>
  );
}

function ErrorRow({ event }: { event: ErrorEvent }) {
  const message = event.failure ? failureMessage(event.failure) : event.message;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-control bg-red-tint px-3 py-2 text-[13px] text-red"
      style={{ animation: "fade-up 300ms var(--ease-out-strong) both" }}
    >
      <CircleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
      <span className="min-w-0 break-words">{message}</span>
    </div>
  );
}

type Group =
  | { kind: "message"; event: MessageEvent }
  | { kind: "error"; event: ErrorEvent }
  | { kind: "plan"; event: ActionEvent }
  | { kind: "questions"; event: ActionEvent }
  | { kind: "skills"; event: ActionEvent }
  | { kind: "actions"; actions: ActionEvent[] };

function skillProposalOutcome(groups: Group[], afterIndex: number): SkillProposalOutcome | undefined {
  for (let i = afterIndex + 1; i < groups.length; i++) {
    const group = groups[i];
    if (group.kind === "message" && group.event.role === "user") {
      return skillReplyOutcome(group.event.text ?? "");
    }
  }
  return undefined;
}

function finishText(action: ActionEvent, obs?: AgentEvent): string | null {
  if (obs?.error) return null;
  const fromArgs = String(action.arguments?.message ?? "").trim();
  const fromObs = (obs?.content ?? "").trim();
  return fromArgs || fromObs || null;
}

function synthesizeToolResponse(
  actions: ActionEvent[],
  observationByCall: Map<string, AgentEvent>,
): string | null {
  for (let i = actions.length - 1; i >= 0; i--) {
    const action = actions[i];
    const obs = action.tool_call_id ? observationByCall.get(action.tool_call_id) : undefined;
    if (action.tool_name === "finish") {
      const text = finishText(action, obs);
      if (text) return text;
    }
  }
  for (let i = actions.length - 1; i >= 0; i--) {
    const action = actions[i];
    if (action.tool_name !== "fanout") continue;
    const obs = action.tool_call_id ? observationByCall.get(action.tool_call_id) : undefined;
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

function collectReplySources(
  groups: Group[],
  observationByCall: Map<string, AgentEvent>,
): Map<string, Source[]> {
  const out = new Map<string, Source[]>();
  let turn: Source[] = [];
  let replyKey: string | null = null;
  const flush = () => {
    if (replyKey && turn.length > 0) out.set(replyKey, uniqueSources(turn));
    turn = [];
    replyKey = null;
  };
  for (const group of groups) {
    if (group.kind === "message") {
      if (group.event.role === "user") flush();
      else if (group.event.role === "assistant" && group.event.text?.trim()) {
        replyKey = eventKey(group.event);
      }
    } else if (group.kind === "actions") {
      for (const action of group.actions) {
        if (action.tool_name !== "web_search" || !action.tool_call_id) continue;
        const obs = observationByCall.get(action.tool_call_id);
        if (obs && isObservation(obs)) turn.push(...observationSources(action.tool_name, obs));
      }
    }
  }
  flush();
  return out;
}

function MessageRow({
  ev,
  isLatestUserTurn,
  sources,
  onRewind,
}: {
  ev: MessageEvent;
  isLatestUserTurn?: boolean;
  sources?: Source[];
  onRewind?: (messageId: string) => void;
}) {
  if (ev.role === "assistant" && !(ev.text ?? "").trim()) return null;

  if (ev.role === "user") {
    const saved = ev.id !== ev.client_event_id;
    return (
      <div className="group/user flex flex-col items-end gap-1">
        <UserBubble
          className="w-full"
          {...(isLatestUserTurn ? { "data-user-turn": "" } : {})}
        >
          {!!ev.attachments?.length && <MessageAttachments attachments={ev.attachments} />}
          {ev.text}
        </UserBubble>
        {onRewind && saved && (
          <button
            type="button"
            onClick={() => onRewind(ev.id)}
            className="flex items-center gap-1 rounded-control px-1.5 py-0.5 text-[12px] text-ink-3 opacity-0 transition-opacity duration-150 group-hover/user:opacity-100 hover:text-ink focus-visible:opacity-100"
          >
            <Undo2Icon className="size-3" />
            Rewind to here
          </button>
        )}
      </div>
    );
  }

  return <AssistantMessage text={ev.text ?? ""} sources={sources} />;
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
    if (group.kind === "message" && group.event.role === "assistant" && (group.event.text ?? "").trim()) {
      return true;
    }
  }
  return false;
}

function AssistantStreamingRow({ since }: { since?: number }) {
  return (
    <div className="flex min-h-32 min-w-0 flex-1 flex-col">
      <LoadingState label="Working" since={since} className="py-1" />
    </div>
  );
}

function groupEvents(events: AgentEvent[]): Group[] {
  const groups: Group[] = [];
  let chain: ActionEvent[] | null = null;
  for (const ev of events) {
    if (isObservation(ev)) continue;
    if (isFanoutWorker(ev)) continue;
    if (!isAction(ev) && !isErrorEvent(ev) && (ev as MessageEvent).role === "system") continue;
    if (isAction(ev) && ev.tool_name === "present_plan") {
      chain = null;
      groups.push({ kind: "plan", event: ev as ActionEvent });
    } else if (isAction(ev) && ev.tool_name === "ask_user") {
      chain = null;
      groups.push({ kind: "questions", event: ev as ActionEvent });
    } else if (isAction(ev) && ev.tool_name === "propose_skills") {
      chain = null;
      groups.push({ kind: "skills", event: ev as ActionEvent });
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

export type ConversationTimelineProps = {
  events: AgentEvent[];
  observationByCall: Map<string, AgentEvent>;
  status: ConversationStatus;
  pendingId?: string;
  pendingQuestionId?: string;
  pendingPlanId?: string;
  pendingSkillsId?: string;
  repo?: string | null;
  livePlan?: { planId: string; steps: PlanStep[] };
  onApprove: () => void;
  onReject: () => void;
  onBuild?: () => void;
  onSelectFile?: (path: string) => void;
  onInstallSkill?: (skill: ProposedSkill) => Promise<{ name: string }>;
  onIncludeSkills?: (names: string[]) => void;
  onSkipSkills?: () => void;
  onRewind?: (messageId: string) => void;
  rewindable?: ReadonlySet<string>;
};

export const ConversationTimeline = memo(function ConversationTimeline({
  events,
  observationByCall,
  status,
  pendingId,
  pendingQuestionId,
  pendingPlanId,
  pendingSkillsId,
  repo,
  livePlan,
  onApprove,
  onReject,
  onBuild,
  onSelectFile,
  onInstallSkill,
  onIncludeSkills,
  onSkipSkills,
  onRewind,
  rewindable,
}: ConversationTimelineProps) {
  const groups = useMemo(() => groupEvents(events), [events]);
  const fanoutWorkersByCall = useMemo(() => buildFanoutWorkerMap(events), [events]);
  const replySources = useMemo(
    () => collectReplySources(groups, observationByCall),
    [groups, observationByCall],
  );
  const userTurnStarts = useMemo(
    () =>
      groups.flatMap((group, i) =>
        group.kind === "message" && group.event.role === "user" ? [i] : [],
      ),
    [groups],
  );
  const lastUserIdx = userTurnStarts.at(-1) ?? -1;
  const live = status === "running" || status === "waiting_for_confirmation";
  const hasActiveToolWork =
    live &&
    events.some(
      (e) => isAction(e) && e.tool_call_id && !observationByCall.has(e.tool_call_id),
    );
  const showAssistantStreaming =
    status === "running" && !hasActiveToolWork && !hasAssistantReplyAfterLastUser(groups);
  const lastUserGroup = lastUserIdx >= 0 ? groups[lastUserIdx] : undefined;
  const runSince =
    lastUserGroup?.kind === "message" && lastUserGroup.event.timestamp
      ? lastUserGroup.event.timestamp * 1000
      : undefined;

  const renderGroup = (group: Group, i: number) => {
    if (group.kind === "actions") {
      const toolResponse = synthesizeToolResponse(group.actions, observationByCall);
      const showToolResponse = toolResponse && !hasLaterAssistantReply(groups, i);
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
          {showToolResponse && <AssistantMessage text={toolResponse} />}
        </Fragment>
      );
    }
    if (group.kind === "plan") {
      return (
        <PlanCard
          key={group.event.id}
          ev={group.event}
          liveSteps={group.event.id === livePlan?.planId ? livePlan.steps : undefined}
          isPending={group.event.id === pendingPlanId}
          onBuild={onBuild}
        />
      );
    }
    if (group.kind === "questions") {
      if (group.event.id === pendingQuestionId) return null;
      return <QuestionsSummary key={group.event.id} ev={group.event} />;
    }
    if (group.kind === "skills") {
      const skills = (group.event.arguments?.skills as ProposedSkill[] | undefined) ?? [];
      if (
        group.event.id === pendingSkillsId &&
        onInstallSkill &&
        onIncludeSkills &&
        onSkipSkills
      ) {
        return (
          <SkillProposalCard
            key={group.event.id}
            repo={repo ?? null}
            reason={String(group.event.arguments?.reason ?? "").trim() || undefined}
            skills={skills}
            onInstall={onInstallSkill}
            onInclude={onIncludeSkills}
            onSkip={onSkipSkills}
          />
        );
      }
      return (
        <SkillProposalSummary
          key={group.event.id}
          skills={skills}
          outcome={skillProposalOutcome(groups, i)}
        />
      );
    }
    if (group.kind === "error") {
      return <ErrorRow key={group.event.id} event={group.event} />;
    }
    const key = eventKey(group.event);
    return (
      <MessageRow
        key={key}
        ev={group.event}
        isLatestUserTurn={i === lastUserIdx}
        sources={replySources.get(key)}
        onRewind={!live && rewindable?.has(group.event.id) ? onRewind : undefined}
      />
    );
  };

  const firstUserIdx = userTurnStarts[0] ?? groups.length;

  return (
    <>
      {groups.slice(0, firstUserIdx).map((group, i) => renderGroup(group, i))}
      {userTurnStarts.map((start, t) => {
        const end = userTurnStarts[t + 1] ?? groups.length;
        const isLast = start === lastUserIdx;
        return (
          <div
            key={eventKey((groups[start] as { event: MessageEvent }).event)}
            data-active-turn={isLast ? "" : undefined}
            className={cn("flex flex-col gap-6", isLast && "min-h-[100cqh]")}
          >
            {groups.slice(start, end).map((group, j) => renderGroup(group, start + j))}
            {isLast && showAssistantStreaming && <AssistantStreamingRow since={runSince} />}
          </div>
        );
      })}
    </>
  );
});
