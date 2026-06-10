"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import {
  api,
  ApiError,
  type AgentEvent,
  type ChangedFile,
  type ConversationStatus,
  type PlanStep,
  type StepStatus,
} from "@/lib/api";
import { useConversation } from "@/lib/queries";
import {
  ConversationTimeline,
  ThinkingIndicator,
} from "@/components/conversation-stream";
import { ChangesPanel } from "@/components/changes-panel";
import { QuestionCard, type Question } from "@/components/question-card";
import { HugeiconsIcon } from "@hugeicons/react";
import { PanelRightIcon } from "@hugeicons/core-free-icons";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
  ConversationTurnAnchor,
} from "@/components/ai-elements/conversation";
import {
  PromptInput,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorLogo,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { CheckIcon, ClipboardListIcon } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";

const BUSY = new Set(["running", "waiting_for_confirmation"]);

// First entry is the default and matches the backend config default.
const MODELS = [
  { id: "gpt-4o-mini", name: "GPT-4o mini" },
  { id: "gpt-4o", name: "GPT-4o" },
  { id: "gpt-4.1", name: "GPT-4.1" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 mini" },
];

export default function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<ConversationStatus>("idle");
  const [input, setInput] = useState("");
  const [model, setModel] = useState(MODELS[0].id);
  const [modelOpen, setModelOpen] = useState(false);
  const [planMode, setPlanMode] = useState(false);
  const [dismissedQuestionId, setDismissedQuestionId] = useState<string | null>(
    null,
  );
  const selectedModel = MODELS.find((m) => m.id === model);
  const [changes, setChanges] = useState<ChangedFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const lastSentText = useRef("");
  const stopping = useRef(false);


  const { data: conversation, error } = useConversation(id);
  const [wsGone, setWsGone] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const exists = !!conversation;
  const missing =
    wsGone || (error instanceof ApiError && error.status === 404);

  useEffect(() => {
    if (!exists) return; 
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let unmounted = false;

    function connect() {
      ws = new WebSocket(api.wsUrl(id));
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.kind === "status") {
          const next = data.status as ConversationStatus;
          setStatus(next);
          // A stop settled: the backend trimmed the cancelled turn, so resync.
          if (stopping.current && !BUSY.has(next)) {
            stopping.current = false;
            api.events(id).then(setEvents).catch(() => {});
          }
          return;
        }
        const ev = data as AgentEvent;
        setEvents((prev) =>
          prev.some((e) => e.id === ev.id) ? prev : [...prev, ev],
        );
      };
      ws.onclose = (e) => {
        setWsConnected(false);
        // 4404: deleted mid-session. Stop reconnecting and fall through to the
        // not-found screen rather than looping against a gone conversation.
        if (e.code === 4404) {
          setWsGone(true);
          return;
        }
        if (unmounted) return;
        reconnectTimer = setTimeout(connect, 1000);
      };
    }
    connect();

    return () => {
      unmounted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [id, exists]);

  const busy = BUSY.has(status);

  const waiting = status === "waiting_for_confirmation";

  const observationByCall = useMemo(() => {
    const map = new Map<string, AgentEvent>();
    for (const e of events) {
      if (e.kind === "observation" && e.tool_call_id) map.set(e.tool_call_id, e);
    }
    return map;
  }, [events]);

  const refreshChanges = useCallback(() => {
    api.changes(id).then(setChanges).catch(() => {});
  }, [id]);

  // Git is the source of truth for changed files; refetch whenever a tool
  // finishes (each observation), since bash can touch files too.
  useEffect(() => {
    refreshChanges();
  }, [refreshChanges, observationByCall.size]);

  function openFile(path: string) {
    setSelectedPath(path);
    setPanelOpen(true);
  }

  const lastUnresolvedAction = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (
        e.kind === "action" &&
        e.tool_call_id &&
        !observationByCall.has(e.tool_call_id)
      ) {
        return e;
      }
    }
    return undefined;
  }, [events, observationByCall]);

  // The agent's last `ask_user` that the user hasn't replied to yet.
  const pendingQuestion = useMemo(() => {
    let candidate: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "ask_user") candidate = e;
      else if (e.kind === "message" && e.role === "user") candidate = undefined;
    }
    return candidate;
  }, [events]);

  const showQuestion =
    !!pendingQuestion &&
    pendingQuestion.id !== dismissedQuestionId &&
    status !== "running";

  // The agent's last presented plan that the user hasn't responded to yet.
  const pendingPlan = useMemo(() => {
    let candidate: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "present_plan") candidate = e;
      else if (e.kind === "message" && e.role === "user") candidate = undefined;
    }
    return candidate;
  }, [events]);

  const showBuild = !!pendingPlan && status !== "running";

  const lastUserTurnId = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.kind === "message" && e.role === "user") return e.id;
    }
    return undefined;
  }, [events]);

  // Live statuses for the latest plan's steps: seeded from its `present_plan`
  // arguments, then folded forward with each `update_plan` call. Replayed
  // events on reconnect rebuild the same state, so this survives refresh.
  const livePlan = useMemo(() => {
    let planEvent: AgentEvent | undefined;
    for (const e of events) {
      if (e.kind === "action" && e.tool_name === "present_plan") planEvent = e;
    }
    if (!planEvent) return undefined;
    const steps = ((planEvent.arguments?.steps as PlanStep[]) ?? []).map(
      (s) => ({ ...s }),
    );
    let afterPlan = false;
    for (const e of events) {
      if (e === planEvent) {
        afterPlan = true;
        continue;
      }
      if (!afterPlan || e.kind !== "action" || e.tool_name !== "update_plan")
        continue;
      const step = Number(e.arguments?.step);
      if (step >= 1 && step <= steps.length)
        steps[step - 1].status = e.arguments?.status as StepStatus;
    }
    return { planId: planEvent.id, steps };
  }, [events]);

  async function sendAnswer(text: string) {
    if (busy) return;
    lastSentText.current = text;
    setStatus("running");
    try {
      await api.sendMessage(id, text, model);
    } catch {
      setStatus("idle");
    }
  }

  function stop() {
    if (!busy) return;
    stopping.current = true;
    // Restore the prompt right away; the turn itself is trimmed once status settles.
    if (lastSentText.current) setInput(lastSentText.current);
    api.stop(id).catch(() => {
      stopping.current = false;
    });
  }

  async function send(message: PromptInputMessage) {
    const text = message.text.trim();
    if (!text || busy) return;
    lastSentText.current = text;
    setInput("");
    setStatus("running");
    const wasPlanMode = planMode;
    setPlanMode(false);
    try {
      await api.sendMessage(id, text, model, wasPlanMode);
    } catch {
      setInput(text);
      setPlanMode(wasPlanMode);
      setStatus("idle");
    }
  }

  if (missing) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm font-medium">This conversation no longer exists.</p>
        <Link href="/" className="text-sm text-muted-foreground underline">
          Back to home
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b bg-background px-4">
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger />
            {conversation?.repo && (
              <span className="truncate text-sm font-medium">
                {conversation.repo}
              </span>
            )}
            {exists && !wsConnected && (
              <span className="flex items-center gap-1.5 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                <Spinner className="size-3" />
                Reconnecting…
              </span>
            )}
          </div>
          {!panelOpen && (
            <button
              type="button"
              onClick={() => setPanelOpen(true)}
              aria-label="Show files panel"
              className="rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            >
              <HugeiconsIcon icon={PanelRightIcon} className="size-4" />
            </button>
          )}

          {panelOpen && (
            <button
            type="button"
            onClick={() => setPanelOpen(false)}
            aria-label="Hide files panel"
            className="rounded p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          >
            <HugeiconsIcon icon={PanelRightIcon} className="size-4" />
          </button>
          )}
        </header>
        <div className="mx-auto flex w-full min-h-0 max-w-3xl flex-1 flex-col px-4 py-2">
          <Conversation>
            <ConversationContent className="space-y-6 px-0 py-0">
              <ConversationTimeline
                events={events}
                observationByCall={observationByCall}
                status={status}
                pendingId={waiting ? lastUnresolvedAction?.id : undefined}
                pendingQuestionId={showQuestion ? pendingQuestion?.id : undefined}
                pendingPlanId={showBuild ? pendingPlan?.id : undefined}
                livePlan={livePlan}
                onBuild={() => {
                  setStatus("running");
                  api.approvePlan(id).catch(() => setStatus("idle"));
                }}
                onApprove={() => {
                  setStatus("running");
                  api.confirm(id, true).catch(() => {});
                }}
                onReject={() => {
                  setStatus("running");
                  api.confirm(id, false).catch(() => {});
                }}
                onSelectFile={openFile}
              />
              {status === "running" && <ThinkingIndicator label="Working…" />}
              <ConversationTurnAnchor turnId={lastUserTurnId} />
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>

          {showQuestion && pendingQuestion && (
            <div className="mt-3">
              <QuestionCard
                key={pendingQuestion.id}
                questions={
                  (pendingQuestion.arguments?.questions as Question[]) ?? []
                }
                onSubmit={sendAnswer}
                onDismiss={() => setDismissedQuestionId(pendingQuestion.id)}
              />
            </div>
          )}

          <PromptInput onSubmit={send} className="mt-3">
        <PromptInputBody>
          <PromptInputTextarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              waiting
                ? "Approve or reject the action above…"
                : showQuestion
                  ? "Or reply directly…"
                  : planMode
                    ? "Describe what to plan…"
                    : "Send a message…"
            }
            disabled={busy}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <ModelSelector open={modelOpen} onOpenChange={setModelOpen}>
              <ModelSelectorTrigger
                render={
                  <PromptInputButton>
                    <ModelSelectorLogo provider="openai" />
                    <ModelSelectorName>
                      {selectedModel?.name ?? "Model"}
                    </ModelSelectorName>
                  </PromptInputButton>
                }
              />
              <ModelSelectorContent className="[&_[data-slot=dialog-close]]:top-2.5 [&_[data-slot=dialog-close]]:right-2.5 [&_[data-slot=command-input-wrapper]]:pr-12">
                <ModelSelectorInput placeholder="Search models…" />
                <ModelSelectorList>
                  <ModelSelectorEmpty>No models found.</ModelSelectorEmpty>
                  <ModelSelectorGroup heading="OpenAI">
                    {MODELS.map((m) => (
                      <ModelSelectorItem
                        key={m.id}
                        value={m.id}
                        onSelect={() => {
                          setModel(m.id);
                          setModelOpen(false);
                        }}
                      >
                        <ModelSelectorLogo provider="openai" />
                        <ModelSelectorName>{m.name}</ModelSelectorName>
                        {model === m.id ? (
                          <CheckIcon className="ml-auto size-4" />
                        ) : (
                          <div className="ml-auto size-4" />
                        )}
                      </ModelSelectorItem>
                    ))}
                  </ModelSelectorGroup>
                </ModelSelectorList>
              </ModelSelectorContent>
            </ModelSelector>
            <PromptInputButton
              variant={planMode ? "default" : "ghost"}
              onClick={() => setPlanMode((on) => !on)}
              aria-pressed={planMode}
              disabled={waiting}
              title="Plan first: explore and propose a plan before making changes"
            >
              <ClipboardListIcon className="size-4" />
              Plan
            </PromptInputButton>
          </PromptInputTools>
          <PromptInputSubmit
            status={busy ? "streaming" : status === "error" ? "error" : undefined}
            onStop={stop}
            disabled={!busy && !input.trim()}
          />
        </PromptInputFooter>
        </PromptInput>
        </div>
      </div>

      {panelOpen && (
        <ChangesPanel
          conversationId={id}
          changes={changes}
          prNumber={conversation?.pr_number ?? null}
          prUrl={conversation?.pr_url ?? null}
          running={status === "running"}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
          onClose={() => setPanelOpen(false)}
          onSynced={refreshChanges}
        />
      )}
    </div>
  );
}
