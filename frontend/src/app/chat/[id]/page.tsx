"use client";

import { use, useEffect, useMemo, useState } from "react";

import Link from "next/link";

import {
  api,
  ApiError,
  type AgentEvent,
  type ChangedFile,
  type ConversationStatus,
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


  const { data: conversation, error } = useConversation(id);
  const [wsGone, setWsGone] = useState(false);
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
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.kind === "status") {
          setStatus(data.status as ConversationStatus);
          return;
        }
        const ev = data as AgentEvent;
        setEvents((prev) =>
          prev.some((e) => e.id === ev.id) ? prev : [...prev, ev],
        );
      };
      ws.onclose = (e) => {
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

  // Git is the source of truth for changed files; refetch whenever a tool
  // finishes (each observation), since bash can touch files too.
  useEffect(() => {
    api.changes(id).then(setChanges).catch(() => {});
  }, [id, observationByCall.size]);

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

  async function sendAnswer(text: string) {
    if (busy) return;
    setStatus("running");
    try {
      await api.sendMessage(id, text, model);
    } catch {
      setStatus("idle");
    }
  }

  async function send(message: PromptInputMessage) {
    const text = message.text.trim();
    if (!text || busy) return;
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
                onBuild={() => sendAnswer("Go ahead and implement the plan.")}
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
            status={status === "error" ? "error" : busy ? "submitted" : undefined}
            disabled={busy || !input.trim()}
          />
        </PromptInputFooter>
        </PromptInput>
        </div>
      </div>

      {panelOpen && (
        <ChangesPanel
          conversationId={id}
          changes={changes}
          selectedPath={selectedPath}
          onSelectPath={setSelectedPath}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </div>
  );
}
